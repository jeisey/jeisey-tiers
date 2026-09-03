"""Reading retained market sources back into arbitrage quotes (ADR-067).

This module is the join that Phase 10 left out, so the tests are mostly about the ways a
join can be *quietly* absent. The defect it exists to end was not a crash: the build ran
green, published a valid artifact, and put three empty columns in front of a reader. So the
cases below are the ones where "nothing happened" is the wrong answer:

* a source that was never captured;
* a source whose snapshot is old enough to be yesterday's market;
* a source whose rows never reached a canonical player.

Each must leave a check behind. None may take the board down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ffdraft.contracts.enums import MarketSignalType
from ffdraft.market.extra import (
    EXTRA_SOURCE_MAX_AGE_HOURS,
    load_extra_quotes,
    quotes_from_snapshot,
)
from ffdraft.market.snapshot import MarketSnapshot, SnapshotManifest
from ffdraft.quality import QualityGate

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
FFC = "fantasyfootballcalculator_adp"


def manifest(*, retrieved_at: datetime, source_id: str = FFC) -> SnapshotManifest:
    return SnapshotManifest(
        manifest_version="1.0",
        source_id=source_id,
        season=2026,
        snapshot_key=retrieved_at.strftime("%Y%m%dT%H%M%SZ"),
        retrieved_at_utc=retrieved_at.isoformat().replace("+00:00", "Z"),
        adapter_version="1.0",
        source_policy_version="1.0",
    )


def row(
    player_id: str | None,
    *,
    adp: float | None = 24.5,
    position: str | None = "RB",
    scoring: str = "HALF",
    **extra: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source_id": FFC,
        "season": 2026,
        "cohort_id": "ffc-half-ppr",
        "market_signal_type": "adp",
        "external_player_id": f"ffc:{player_id or 'x'}",
        "player_id": player_id,
        "display_name": "A Player",
        "position": position,
        "team": "BUF",
        "average_pick": adp,
        "market_rank": None,
        "min_pick": None,
        "max_pick": None,
        "adp_sd": 4.2,
        "consensus_rank_mean": None,
        "consensus_rank_min": None,
        "consensus_rank_max": None,
        "consensus_rank_sd": None,
        "sample_size": 1794,
        "selection_pct": None,
        "scoring_preset": scoring,
        "league_size": None,
        "aggregation_window_type": "rolling",
        "aggregation_window_days": 7,
        "entity_kind": "player",
        "raw_position": position,
        "source_display_name": "A Player",
        "source_team": "BUF",
        "source_format_detail": "format=half-ppr",
        "quality_flags": [],
    }
    base.update(extra)
    return base


def snapshot(rows: list[dict[str, Any]], *, age_hours: float = 1.0) -> MarketSnapshot:
    retrieved = NOW - timedelta(hours=age_hours)
    return MarketSnapshot(manifest=manifest(retrieved_at=retrieved), rows=tuple(rows))


class _Store:
    """The two calls `load_extra_quotes` makes, and nothing else."""

    def __init__(self, snapshots: dict[str, MarketSnapshot | None | Exception]) -> None:
        self._snapshots = snapshots
        self.root = "fake"

    def read_latest(self, source_id: str, season: int) -> MarketSnapshot | None:
        found = self._snapshots.get(source_id)
        if isinstance(found, Exception):
            raise found
        return found


# --------------------------------------------------------------------------------------
# Quoting
# --------------------------------------------------------------------------------------


def test_a_resolved_row_becomes_a_quote_keyed_by_preset_and_player() -> None:
    quotes, _ = quotes_from_snapshot(snapshot([row("gsis:001")]))

    quote = quotes[("HALF", "gsis:001")]
    assert quote.source_id == FFC
    assert quote.signal_type is MarketSignalType.ADP
    assert quote.market_adp == 24.5
    assert quote.adp_sd == 4.2
    # FFC's `teams=` is accepted and ignored, so a league size is never claimed (ADR-056).
    assert quote.league_size is None
    assert quote.aggregation_window_type == "rolling"
    assert quote.aggregation_window_days == 7
    # The observation instant travels with the quote; a card prints it beside the number.
    assert quote.snapshot_at_utc.startswith("2026-09-03")


def test_an_unresolved_row_is_counted_rather_than_quoted() -> None:
    """Identity failures are measured separately, never hidden in the denominator."""
    quotes, memberships = quotes_from_snapshot(snapshot([row("gsis:001"), row(None)]))

    assert set(quotes) == {("HALF", "gsis:001")}
    assert memberships[0].unresolved == 1
    assert memberships[0].resolved == frozenset({"gsis:001"})


def test_a_kicker_is_quoted_but_never_counted_as_missing() -> None:
    """The gate asks "did the board drop a player it could have valued?"

    A kicker was never eligible for a V1 board, so counting one into membership would fail a
    production build over a player the model is not supposed to rank. He still gets a quote:
    if a row for him ever reaches the board, it carries his real price rather than a blank.
    """
    quotes, memberships = quotes_from_snapshot(
        snapshot([row("gsis:001"), row("gsis:kicker", position="K")]),
    )

    assert ("HALF", "gsis:kicker") in quotes
    assert memberships[0].resolved == frozenset({"gsis:001"})


def test_membership_takes_the_top_n_by_the_sources_own_ordering() -> None:
    rows = [row(f"gsis:{i:03d}", adp=float(i)) for i in range(1, 6)]
    _, memberships = quotes_from_snapshot(snapshot(rows), top_depth=2)

    assert memberships[0].resolved == frozenset({"gsis:001", "gsis:002"})
    assert memberships[0].depth == 2


# --------------------------------------------------------------------------------------
# Absence is reported, never silent
# --------------------------------------------------------------------------------------


def test_a_source_that_was_never_captured_is_a_named_warning() -> None:
    gate = QualityGate()
    load = load_extra_quotes(
        _Store({FFC: None}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
    )

    assert load.quotes == {}
    check = next(c for c in gate.checks if c.check_id == "market.extra_source_absent")
    assert check.severity == "warning", "one missing market must not fail the whole refresh"
    assert FFC in check.message
    assert load.sources == [{"source_id": FFC, "status": "absent", "rows": 0}]


def test_a_stale_snapshot_does_not_price_todays_board() -> None:
    """Yesterday's market beside today's is worse than an honestly missing column."""
    gate = QualityGate()
    stale = snapshot([row("gsis:001")], age_hours=EXTRA_SOURCE_MAX_AGE_HOURS + 1)
    load = load_extra_quotes(
        _Store({FFC: stale}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
    )

    assert load.quotes == {}
    check = next(c for c in gate.checks if c.check_id == "market.extra_source_stale")
    assert check.severity == "warning"
    assert load.sources[0]["status"] == "stale"


def test_a_snapshot_inside_the_freshness_rule_prices_the_board() -> None:
    gate = QualityGate()
    fresh = snapshot([row("gsis:001")], age_hours=EXTRA_SOURCE_MAX_AGE_HOURS - 1)
    load = load_extra_quotes(
        _Store({FFC: fresh}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
    )

    assert load.source_ids == (FFC,)
    assert load.quotes[FFC][("HALF", "gsis:001")].market_adp == 24.5
    assert load.sources[0]["status"] == "priced"
    assert load.sources[0]["quoted_players"] == 1


def test_a_snapshot_that_resolved_nobody_is_reported_rather_than_priced() -> None:
    gate = QualityGate()
    load = load_extra_quotes(
        _Store({FFC: snapshot([row(None), row(None)])}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
    )

    assert load.quotes == {}
    check = next(c for c in gate.checks if c.check_id == "market.extra_source_unresolved")
    assert "prices nothing" in check.message


def test_a_corrupt_store_read_is_a_check_rather_than_a_crash() -> None:
    """A hash mismatch is corruption worth seeing, and not worth losing the board over."""
    gate = QualityGate()
    load = load_extra_quotes(
        _Store({FFC: OSError("content hash does not match")}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
    )

    assert load.quotes == {}
    check = next(c for c in gate.checks if c.check_id == "market.extra_source_unreadable")
    assert "content hash" in check.message
