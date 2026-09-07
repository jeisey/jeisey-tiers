"""Retained Phase-10 source snapshots, read back as arbitrage quotes.

**Boundary module.** Reads market evidence and intrinsic outputs; never the reverse.

Phase 10 built the capture, the contracts, the identity linkage and the comparison maths for
a second ADP source, and then wired none of it into the production build: `pipeline/market.py`
called :func:`~ffdraft.arbitrage.build.build_arbitrage_records` with no ``extra_quotes``, so
every published row carried MyFantasyLeague and nothing else while the page rendered columns
for markets the artifact did not contain. This module is the missing join.

It is deliberately **read-only over the store**. The capture path writes; this reads what was
written, on the same append-only discipline that makes an arbitrage board reproducible from
evidence months later (ADR-038). A source that was never captured, or whose snapshot is older
than the freshness rule allows, contributes nothing and is *reported* — it never silently
degrades into a missing column, because that is the failure this module exists to end.

Two outputs, from one read:

``extra_quotes``
    ``source_id -> (scoring_preset, player_id) -> SourceQuote``, which
    :func:`~ffdraft.arbitrage.build.build_arbitrage_records` turns into the ``markets`` array
    and the cross-market summary.

``memberships``
    each source's top-:data:`~ffdraft.market.surface.MARKET_TOP_DEPTH` population per scoring
    preset, which the surface universe uses to decide who is publicly relevant regardless of
    where the intrinsic model ranked them (ADR-063).

``histories``
    each source's trailing retained window and its `phase5_trend_v1` slopes, from
    :mod:`ffdraft.market.history` — the same machinery MyFantasyLeague uses, not a second
    implementation of it.

**The version of this module that shipped read only the latest snapshot.** A second source
therefore arrived with a price and no past: its ``market_trend`` was ``None`` because nothing
had ever computed one, and `market_trend_series.json` carried no record for it at all. On a
player card that reads as "current FFC ADP 24.5" beside "0 snapshots so far" — a sentence
about our own plumbing, phrased as a fact about the market (ADR-081). The window is loaded
here now, and the trend it produces is attached to the source's own quotes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import CORE_POSITIONS, MarketSignalType, Position, Severity
from ffdraft.market.comparison import SourceQuote
from ffdraft.market.history import (
    RetainedHistory,
    build_retained_history,
    cohorts_by_scoring_preset,
    expand_cohorts_over_league_sizes,
    load_trend_window,
)
from ffdraft.market.snapshot import MarketSnapshot, MarketSnapshotStore
from ffdraft.market.surface import MARKET_TOP_DEPTH, MarketMembership
from ffdraft.market.trend import INSUFFICIENT_TREND_HISTORY, TREND_RULE, TrendResult
from ffdraft.quality import QualityGate

__all__ = [
    "EXTRA_SOURCE_MAX_AGE_HOURS",
    "ExtraMarketLoad",
    "load_extra_quotes",
    "quotes_from_snapshot",
]

#: How stale a retained source snapshot may be and still price a published board.
#:
#: The daily refresh captures every source in the same job, so a snapshot older than this
#: means that source's capture failed or was skipped — and a board that quietly prices
#: yesterday's market beside today's is worse than one that says a source is missing. Two
#: days rather than one so a single failed capture degrades to a warning with a visible
#: reason rather than to a silently absent column.
EXTRA_SOURCE_MAX_AGE_HOURS = 48


@dataclass
class ExtraMarketLoad:
    """What the retained non-MFL sources contributed to this build."""

    quotes: dict[str, dict[tuple[str, str], SourceQuote]] = field(default_factory=dict)
    memberships: list[MarketMembership] = field(default_factory=list)
    #: Per-source provenance, merged into `build_metadata.json` so a reader can see which
    #: markets priced the board and when each was observed.
    sources: list[dict[str, Any]] = field(default_factory=list)
    #: Each priced source's trailing retained window and its trends, so the series writer can
    #: publish a chart history for it (ADR-081). Keyed by source id.
    histories: dict[str, RetainedHistory] = field(default_factory=dict)

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.quotes))


def _is_core(position: Any) -> bool:
    """Whether a retained row names a position the intrinsic board ranks."""
    if position is None:
        return False
    parsed = Position.parse(str(position))
    return parsed in CORE_POSITIONS


def quotes_from_snapshot(
    snapshot: MarketSnapshot,
    *,
    top_depth: int = MARKET_TOP_DEPTH,
    trends: Mapping[str, Mapping[str, TrendResult]] | None = None,
) -> tuple[dict[tuple[str, str], SourceQuote], list[MarketMembership]]:
    """One retained snapshot's rows as quotes, plus its top-N membership per preset.

    Rows that never reached a canonical player are skipped for quoting — an unidentified
    player cannot be joined to a fair rank — but they are *counted* into
    :attr:`~ffdraft.market.surface.MarketMembership.unresolved`, because roadmap 10.5 is
    explicit that identity failures must not vanish inside a coverage denominator.

    ``trends`` is this source's own ``cohort_id -> player_id -> TrendResult`` map, computed
    over its own retained window. Absent — or present with no result for a player — the quote
    carries ``market_trend = None`` **and** the ``insufficient_trend_history`` flag, so the
    null says why it is null instead of reading as "this market has not moved".
    """
    by_cohort = trends or {}
    quotes: dict[tuple[str, str], SourceQuote] = {}
    by_preset: dict[tuple[str, str, MarketSignalType], list[tuple[float, str]]] = {}
    unresolved: dict[tuple[str, str, MarketSignalType], int] = {}
    observed_at = snapshot.manifest.retrieved_at_utc

    for row in snapshot.rows:
        source_id = str(row["source_id"])
        scoring = str(row["scoring_preset"])
        signal = MarketSignalType(str(row["market_signal_type"]))
        bucket = (source_id, scoring, signal)
        player_id = row.get("player_id")
        if not player_id:
            unresolved[bucket] = unresolved.get(bucket, 0) + 1
            continue

        adp = row.get("average_pick")
        rank = row.get("market_rank")
        cohort_id = str(row["cohort_id"])
        trend = by_cohort.get(cohort_id, {}).get(str(player_id))
        quotes[(scoring, str(player_id))] = SourceQuote(
            source_id=source_id,
            signal_type=signal,
            player_id=str(player_id),
            scoring_preset=scoring,
            market_adp=float(adp) if adp is not None else None,
            market_rank=int(rank) if rank is not None else None,
            sample_size=row.get("sample_size"),
            adp_sd=row.get("adp_sd"),
            adp_low=row.get("min_pick"),
            adp_high=row.get("max_pick"),
            consensus_rank_mean=row.get("consensus_rank_mean"),
            consensus_rank_min=row.get("consensus_rank_min"),
            consensus_rank_max=row.get("consensus_rank_max"),
            consensus_rank_sd=row.get("consensus_rank_sd"),
            # Null and not claimable for FFC: `teams=` is accepted and ignored, so the rows
            # are one population however the request was phrased (ADR-056).
            league_size=row.get("league_size"),
            aggregation_window_type=str(row["aggregation_window_type"]),
            aggregation_window_days=row.get("aggregation_window_days"),
            cohort_id=cohort_id,
            cohort_detail=str(row.get("source_format_detail") or ""),
            snapshot_at_utc=observed_at,
            # This source's own slope over this source's own retained window. Never borrowed:
            # a null here means *this* market has not yet supplied three observation days
            # spanning three days, which is a different fact from another market's number.
            market_trend=trend.trend if trend is not None else None,
            quality_flags=tuple(
                dict.fromkeys(
                    [
                        *(row.get("quality_flags") or ()),
                        *(
                            trend.quality_flags
                            if trend is not None
                            else (INSUFFICIENT_TREND_HISTORY,)
                        ),
                    ],
                ),
            ),
        )
        # The ordering key is the source's own: an ADP source is ranked by pick, a ranking
        # source by rank. Sorting an ECR by a null ADP would make its top-N arbitrary.
        order = adp if adp is not None else rank
        # Membership drives a **critical** surface gate, and its question is "did the board
        # drop a player it could have valued?" A kicker or a team defence was never eligible
        # for a V1 board (`CORE_POSITIONS`, PRD 4), so counting one as missing would fail a
        # production build for a player the model is not supposed to rank. Quoting is
        # unaffected: if such a row somehow reaches an arbitrage record it still carries its
        # own price.
        if order is not None and _is_core(row.get("position")):
            by_preset.setdefault(bucket, []).append((float(order), str(player_id)))

    memberships = [
        MarketMembership(
            source_id=source_id,
            signal_type=signal,
            scoring_preset=scoring,
            resolved=frozenset(player_id for _, player_id in sorted(entries)[: max(top_depth, 0)]),
            unresolved=unresolved.get((source_id, scoring, signal), 0),
            depth=top_depth,
        )
        for (source_id, scoring, signal), entries in sorted(
            by_preset.items(),
            key=lambda item: (item[0][0], item[0][1], str(item[0][2])),
        )
    ]
    return quotes, memberships


def load_extra_quotes(
    store: MarketSnapshotStore,
    *,
    season: int,
    source_ids: Sequence[str],
    now: datetime,
    gate: QualityGate,
    league_sizes: Sequence[int] = (),
    max_age_hours: int = EXTRA_SOURCE_MAX_AGE_HOURS,
    top_depth: int = MARKET_TOP_DEPTH,
) -> ExtraMarketLoad:
    """Read every requested source's retained window into quotes, trends and a history.

    A source with no snapshot, or with one older than ``max_age_hours``, is a **warning and
    a recorded absence**, not a silent one. The build still publishes — one market missing
    must not take the board down — but the reason is in the quality gate and in
    `build_metadata.json`, and the frontend renders only the markets the artifact actually
    carries, so a missing source disappears from the page rather than becoming a column of
    dashes.

    ``league_sizes`` are the team counts the board publishes. They are needed only to key the
    cohort map the way the series writer asks for it; a source that does not observe league
    size maps every one of them onto the same cohort, which is the honest encoding rather
    than a shortcut (:func:`~ffdraft.market.history.expand_cohorts_over_league_sizes`).
    """
    load = ExtraMarketLoad()
    for source_id in source_ids:
        snapshot = _read_latest(store, source_id=source_id, season=season, gate=gate)
        if snapshot is None:
            load.sources.append({"source_id": source_id, "status": "absent", "rows": 0})
            continue

        age = now - snapshot.manifest.retrieved_at
        if age > timedelta(hours=max_age_hours):
            gate.add(
                QualityCheck.fail(
                    "market.extra_source_stale",
                    stage="market.extra",
                    message=(
                        f"{source_id}: the latest retained snapshot is "
                        f"{age.total_seconds() / 3600:.1f}h old; it is not priced into this "
                        "board"
                    ),
                    observed=snapshot.manifest.retrieved_at_utc,
                    expected=f"within {max_age_hours}h of the build",
                    severity=Severity.WARNING,
                ),
            )
            load.sources.append(
                {
                    "source_id": source_id,
                    "status": "stale",
                    "observed_at_utc": snapshot.manifest.retrieved_at_utc,
                    "rows": len(snapshot.rows),
                },
            )
            continue

        history = _source_history(
            store,
            snapshot,
            source_id=source_id,
            season=season,
            league_sizes=league_sizes,
            gate=gate,
        )
        quotes, memberships = quotes_from_snapshot(
            snapshot,
            top_depth=top_depth,
            trends=history.trend_by_cohort,
        )
        if not quotes:
            gate.add(
                QualityCheck.fail(
                    "market.extra_source_unresolved",
                    stage="market.extra",
                    message=(
                        f"{source_id}: the retained snapshot resolved no player to a "
                        "canonical id, so it prices nothing"
                    ),
                    observed=f"0 of {len(snapshot.rows)} row(s)",
                    expected="at least one resolved player",
                    severity=Severity.WARNING,
                ),
            )
            load.sources.append(
                {"source_id": source_id, "status": "unresolved", "rows": len(snapshot.rows)},
            )
            continue

        load.quotes[source_id] = quotes
        load.memberships.extend(memberships)
        load.histories[source_id] = history
        load.sources.append(
            {
                "source_id": source_id,
                "status": "priced",
                "observed_at_utc": snapshot.manifest.retrieved_at_utc,
                "snapshot_key": snapshot.manifest.snapshot_key,
                "rows": len(snapshot.rows),
                "quoted_players": len(quotes),
                "presets": sorted({scoring for scoring, _ in quotes}),
                # The evidence behind this source's chart, and behind the null when its slope
                # is not yet computable. Published so "0 snapshots so far" can never again be
                # the only thing a reader is told (ADR-081).
                "trend_history_snapshots": len(history.snapshots),
                "trend_available": history.trend_available,
                "trend_rule_version": TREND_RULE.version,
            },
        )
    return load


def _source_history(
    store: MarketSnapshotStore,
    snapshot: MarketSnapshot,
    *,
    source_id: str,
    season: int,
    league_sizes: Sequence[int],
    gate: QualityGate,
) -> RetainedHistory:
    """This source's trailing retained window and its `phase5_trend_v1` slopes.

    The window is anchored on the source's **own** newest snapshot rather than on the build
    clock or on MyFantasyLeague's: sources are captured by different jobs and can be hours
    apart, and asking the frozen rule about days a source has no evidence for would not make
    its history longer.

    A read failure degrades to "this source has a price and no history yet", with the reason
    recorded. A market that cannot be charted must never take the board down.
    """
    by_scoring, ambiguous = cohorts_by_scoring_preset(snapshot)
    if ambiguous:
        # More than one cohort per scoring preset means this source needs a selection rule of
        # its own, as MyFantasyLeague has (ADR-039). Picking one here would mix populations,
        # which is the one thing `phase5_trend_v1` forbids outright.
        gate.add(
            QualityCheck.fail(
                "market.extra_source_cohort_ambiguous",
                stage="market.extra",
                message=(
                    f"{source_id}: a scoring preset is served by more than one retained "
                    "cohort, so no trend is computed for it; a cohort selection rule is "
                    "needed before this source can carry a history"
                ),
                observed="; ".join(
                    f"{scoring}: {', '.join(cohorts)}"
                    for scoring, cohorts in sorted(ambiguous.items())
                ),
                expected="one cohort per scoring preset",
                severity=Severity.WARNING,
            ),
        )
    if not by_scoring:
        # Every source whose rows tag their own scoring preset resolves here. One whose rows
        # do not — MyFantasyLeague, whose cohorts are filter-defined and mapped to presets by
        # the ADR-039 selection rule — needs that rule rather than this derivation, and must
        # not simply lose its chart in silence.
        gate.add(
            QualityCheck.fail(
                "market.extra_source_cohort_underivable",
                stage="market.extra",
                message=(
                    f"{source_id}: no scoring preset could be resolved to a single retained "
                    "cohort, so this market is priced without a history"
                ),
                observed=f"{len(snapshot.rows)} retained row(s)",
                expected="rows carrying scoring_preset and cohort_id",
                severity=Severity.WARNING,
            ),
        )
    cohorts = expand_cohorts_over_league_sizes(by_scoring, league_sizes or (0,))
    try:
        window = load_trend_window(
            store,
            source_id=source_id,
            season=season,
            now=snapshot.retrieved_at,
            rule_window_days=TREND_RULE.window_days,
        )
    except Exception as error:  # noqa: BLE001 - a bad read must not take the board down
        gate.add(
            QualityCheck.fail(
                "market.extra_source_history_unreadable",
                stage="market.extra",
                message=(
                    f"{source_id}: the retained trend window could not be read, so this "
                    f"market is priced without a history: {error}"
                ),
                observed=type(error).__name__,
                expected="a readable retained window",
                severity=Severity.WARNING,
            ),
        )
        window = [snapshot]
    return build_retained_history(
        window or [snapshot],
        source_id=source_id,
        cohorts=cohorts,
        now=snapshot.retrieved_at,
        rule=TREND_RULE,
    )


def _read_latest(
    store: MarketSnapshotStore,
    *,
    source_id: str,
    season: int,
    gate: QualityGate,
) -> MarketSnapshot | None:
    """The newest retained snapshot, or ``None`` with the reason recorded.

    A store read can fail for a reason worth seeing — a hash mismatch is corruption, not an
    absence — so the exception is turned into a check rather than into a crash that would
    take the whole board down with it.
    """
    try:
        snapshot = store.read_latest(source_id, season)
    except Exception as error:  # noqa: BLE001 - a bad read must not take the board down
        gate.add(
            QualityCheck.fail(
                "market.extra_source_unreadable",
                stage="market.extra",
                message=f"{source_id}: the retained snapshot could not be read: {error}",
                observed=type(error).__name__,
                expected="a readable snapshot",
                severity=Severity.WARNING,
            ),
        )
        return None
    if snapshot is None:
        gate.add(
            QualityCheck.fail(
                "market.extra_source_absent",
                stage="market.extra",
                message=(
                    f"{source_id}: no retained snapshot for season {season}; this board is "
                    "priced without it"
                ),
                observed="no snapshot",
                expected="a snapshot from today's capture",
                severity=Severity.WARNING,
            ),
        )
    return snapshot


def merge_membership_metadata(load: ExtraMarketLoad) -> list[Mapping[str, Any]]:
    """The per-source provenance, ready to merge into `build_metadata.json`."""
    return list(load.sources)
