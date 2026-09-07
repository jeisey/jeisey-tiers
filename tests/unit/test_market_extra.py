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
from ffdraft.market.snapshot import MarketSnapshot, SnapshotManifest, snapshot_key
from ffdraft.quality import QualityGate

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
FFC = "fantasyfootballcalculator_adp"


def manifest(*, retrieved_at: datetime, source_id: str = FFC) -> SnapshotManifest:
    return SnapshotManifest(
        manifest_version="1.0",
        source_id=source_id,
        season=2026,
        # The store's own key format, because `load_trend_window` parses these back into
        # instants to bound the window. A key this project could not have written would make
        # the window unreadable and quietly reduce the history to one snapshot.
        snapshot_key=snapshot_key(retrieved_at),
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
    """The calls `load_extra_quotes` makes, and nothing else.

    It reads a *window* as well as a latest snapshot now: a second market's trend is computed
    over its own retained history, and a stub that only served the newest capture would let
    the very defect this module was fixed for pass unnoticed (ADR-081).
    """

    def __init__(
        self,
        snapshots: dict[str, MarketSnapshot | None | Exception],
        windows: dict[str, list[MarketSnapshot]] | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._windows = windows or {}
        self.root = "fake"

    def read_latest(self, source_id: str, season: int) -> MarketSnapshot | None:
        found = self._snapshots.get(source_id)
        if isinstance(found, Exception):
            raise found
        return found

    def keys(self, source_id: str, season: int) -> list[str]:
        return [item.manifest.snapshot_key for item in self._window_for(source_id)]

    def read_window(
        self,
        source_id: str,
        season: int,
        *,
        keys: list[str] | None = None,
    ) -> list[MarketSnapshot]:
        wanted = set(keys) if keys is not None else None
        return [
            item
            for item in self._window_for(source_id)
            if wanted is None or item.manifest.snapshot_key in wanted
        ]

    def _window_for(self, source_id: str) -> list[MarketSnapshot]:
        if source_id in self._windows:
            return self._windows[source_id]
        found = self._snapshots.get(source_id)
        return [found] if isinstance(found, MarketSnapshot) else []


def _window(offsets_hours: tuple[float, ...], *, base_adp: float = 24.5) -> list[MarketSnapshot]:
    """A retained cadence for one player, measured back from ``NOW``, drifting earlier."""
    return [
        snapshot([row("gsis:001", adp=round(base_adp + offset * 0.05, 2))], age_hours=offset)
        for offset in sorted(offsets_hours, reverse=True)
    ]


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


# --------------------------------------------------------------------------------------
# A second market's own history, and its own slope (ADR-081)
# --------------------------------------------------------------------------------------
#
# The version of this module that shipped read only `read_latest`. Every quote it produced
# therefore carried `market_trend=None` — never computed, not merely unqualified — and the
# player card filled that null in from MyFantasyLeague. These are the cases that decide
# whether the null is a *measurement* or a plumbing gap.


def test_a_qualifying_window_gives_the_source_its_own_slope() -> None:
    gate = QualityGate()
    window = _window((96.0, 72.0, 48.0, 24.0, 1.0))
    load = load_extra_quotes(
        _Store({FFC: window[-1]}, {FFC: window}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
        league_sizes=(10, 12, 14),
    )

    quote = load.quotes[FFC][("HALF", "gsis:001")]
    assert quote.market_trend is not None
    # Every ADP fell across the window, so he is being taken earlier.
    assert quote.market_trend > 0
    assert "insufficient_trend_history" not in quote.quality_flags
    assert load.histories[FFC].snapshot_keys == tuple(item.manifest.snapshot_key for item in window)
    assert load.sources[0]["trend_history_snapshots"] == 5
    assert load.sources[0]["trend_available"] is True


def test_a_real_history_too_short_to_fit_keeps_a_null_slope_and_says_why() -> None:
    """Observations exist; the elapsed span does not reach three days. Both are true at once.

    This is the state the frozen rule is *supposed* to produce, and the state the card must
    render as "collecting" rather than filling in from another market.
    """
    gate = QualityGate()
    window = _window((62.0, 55.0, 38.0, 19.0, 1.0))
    load = load_extra_quotes(
        _Store({FFC: window[-1]}, {FFC: window}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
        league_sizes=(12,),
    )

    quote = load.quotes[FFC][("HALF", "gsis:001")]
    assert quote.market_trend is None
    assert "insufficient_trend_history" in quote.quality_flags
    # And the evidence is still there to draw: five retained observations, four of them days.
    history = load.histories[FFC]
    assert len(history.observations_for("ffc-half-ppr")) == 5
    assert load.sources[0]["trend_available"] is False


def test_a_scoring_preset_maps_to_one_cohort_across_every_league_size() -> None:
    gate = QualityGate()
    window = _window((48.0, 24.0, 1.0))
    load = load_extra_quotes(
        _Store({FFC: window[-1]}, {FFC: window}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
        league_sizes=(10, 12, 14),
    )

    cohorts = load.histories[FFC].cohorts
    assert cohorts == {
        ("HALF", 10): "ffc-half-ppr",
        ("HALF", 12): "ffc-half-ppr",
        ("HALF", 14): "ffc-half-ppr",
    }
    # ...and nothing anywhere claims FFC observed a league size.
    assert load.quotes[FFC][("HALF", "gsis:001")].league_size is None


def test_a_source_whose_rows_name_no_cohort_loses_its_chart_loudly() -> None:
    """MyFantasyLeague's rows are like this: filter-defined cohorts, no scoring tag.

    Such a source needs the ADR-039 selection rule rather than this derivation. The board
    still publishes its price; what must not happen is the history disappearing in silence,
    which is how this whole defect stayed invisible for two phases.
    """
    gate = QualityGate()
    untagged = snapshot([row("gsis:001", scoring="HALF", cohort_id="")])
    load = load_extra_quotes(
        _Store({FFC: untagged}, {FFC: [untagged]}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
        league_sizes=(12,),
    )

    assert load.quotes[FFC][("HALF", "gsis:001")].market_trend is None
    check = next(c for c in gate.checks if c.check_id == "market.extra_source_cohort_underivable")
    assert check.severity == "warning"


def test_two_cohorts_for_one_scoring_preset_are_refused_rather_than_guessed_at() -> None:
    gate = QualityGate()
    mixed = snapshot(
        [
            row("gsis:001", scoring="HALF", cohort_id="ffc-half-ppr"),
            row("gsis:002", scoring="HALF", cohort_id="ffc-half-ppr-mock"),
        ],
    )
    load_extra_quotes(
        _Store({FFC: mixed}, {FFC: [mixed]}),
        season=2026,
        source_ids=(FFC,),
        now=NOW,
        gate=gate,
        league_sizes=(12,),
    )

    check = next(c for c in gate.checks if c.check_id == "market.extra_source_cohort_ambiguous")
    assert "ffc-half-ppr" in check.observed
    assert check.severity == "warning"
