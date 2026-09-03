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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import CORE_POSITIONS, MarketSignalType, Position, Severity
from ffdraft.market.comparison import SourceQuote
from ffdraft.market.snapshot import MarketSnapshot, MarketSnapshotStore
from ffdraft.market.surface import MARKET_TOP_DEPTH, MarketMembership
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
) -> tuple[dict[tuple[str, str], SourceQuote], list[MarketMembership]]:
    """One retained snapshot's rows as quotes, plus its top-N membership per preset.

    Rows that never reached a canonical player are skipped for quoting — an unidentified
    player cannot be joined to a fair rank — but they are *counted* into
    :attr:`~ffdraft.market.surface.MarketMembership.unresolved`, because roadmap 10.5 is
    explicit that identity failures must not vanish inside a coverage denominator.
    """
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
            cohort_id=str(row["cohort_id"]),
            cohort_detail=str(row.get("source_format_detail") or ""),
            snapshot_at_utc=observed_at,
            quality_flags=tuple(row.get("quality_flags") or ()),
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
    max_age_hours: int = EXTRA_SOURCE_MAX_AGE_HOURS,
    top_depth: int = MARKET_TOP_DEPTH,
) -> ExtraMarketLoad:
    """Read every requested source's latest retained snapshot into quotes.

    A source with no snapshot, or with one older than ``max_age_hours``, is a **warning and
    a recorded absence**, not a silent one. The build still publishes — one market missing
    must not take the board down — but the reason is in the quality gate and in
    `build_metadata.json`, and the frontend renders only the markets the artifact actually
    carries, so a missing source disappears from the page rather than becoming a column of
    dashes.
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

        quotes, memberships = quotes_from_snapshot(snapshot, top_depth=top_depth)
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
        load.sources.append(
            {
                "source_id": source_id,
                "status": "priced",
                "observed_at_utc": snapshot.manifest.retrieved_at_utc,
                "snapshot_key": snapshot.manifest.snapshot_key,
                "rows": len(snapshot.rows),
                "quoted_players": len(quotes),
                "presets": sorted({scoring for scoring, _ in quotes}),
            },
        )
    return load


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
