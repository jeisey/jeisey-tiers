"""Source-relative comparisons and the cross-market summary (Phase 10, ADR-065).

Release 2's guardrail 2.3 forbids averaging unlike market signals into an opaque consensus,
and roadmap 10.4 forbids letting an expert ranking into an ADP aggregate. Both are easy to
state and easy to violate by accident three refactors later, so the tests below are mostly
about what must *not* happen to a number.
"""

from __future__ import annotations

import math

import pytest

from ffdraft.arbitrage.baseline import rank_gap, regional_value_gap
from ffdraft.contracts.enums import MarketSignalType
from ffdraft.market.comparison import (
    COMPARISON_METHOD_VERSION,
    SourceQuote,
    cross_market_summary,
    ecr_comparison,
    quotes_from_snapshot_rows,
    source_comparison,
    source_comparisons,
)

FFC = "fantasyfootballcalculator_adp"
MFL = "myfantasyleague_adp"
FP = "fantasypros_ecr"


def adp(source_id: str, value: float, **kwargs) -> SourceQuote:
    return SourceQuote(
        source_id=source_id,
        signal_type=MarketSignalType.ADP,
        player_id="gsis:1",
        scoring_preset="HALF",
        market_adp=value,
        **kwargs,
    )


def ecr(rank: int, **kwargs) -> SourceQuote:
    return SourceQuote(
        source_id=FP,
        signal_type=MarketSignalType.ECR,
        player_id="gsis:1",
        scoring_preset="HALF",
        market_rank=rank,
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# The roadmap's own worked example
# --------------------------------------------------------------------------------------


def test_the_roadmap_worked_example_reproduces_exactly() -> None:
    """Roadmap 10.4 states the numbers a player should legitimately be able to read.

    Reproducing them is the cheapest possible check that the multi-source layer means what
    the specification says it means.
    """
    quotes = [adp(FFC, 61.0), adp(MFL, 53.0), ecr(49)]
    comparisons = source_comparisons(quotes, fair_rank=42)

    assert comparisons[FFC].rank_gap == 19.0
    assert comparisons[MFL].rank_gap == 11.0
    assert ecr_comparison(quotes[2], fair_rank=42).ecr_gap == 7.0


# --------------------------------------------------------------------------------------
# ECR never becomes a price
# --------------------------------------------------------------------------------------


def test_an_ecr_quote_produces_no_adp_comparison() -> None:
    assert source_comparison(ecr(49), fair_rank=42) is None


def test_an_adp_quote_produces_no_ecr_comparison() -> None:
    assert ecr_comparison(adp(FFC, 61.0), fair_rank=42) is None


def test_ecr_is_excluded_from_every_cross_market_adp_field() -> None:
    """The rule that most needs a test, because the failure would look plausible."""
    with_ecr = cross_market_summary([adp(FFC, 61.0), adp(MFL, 53.0), ecr(10)], player_id="gsis:1")
    without = cross_market_summary([adp(FFC, 61.0), adp(MFL, 53.0)], player_id="gsis:1")
    assert with_ecr.to_dict() == without.to_dict()
    assert FP not in with_ecr.sources_available


def test_an_ecr_only_player_has_no_cross_market_price_at_all() -> None:
    summary = cross_market_summary([ecr(10)], player_id="gsis:1")
    assert summary.sources_available == ()
    assert summary.market_adp_median is None
    assert summary.market_disagreement_range is None


def test_the_ecr_gap_field_is_not_named_rank_gap() -> None:
    """A caller reaching for the wrong field gets an error, not a plausible number."""
    comparison = ecr_comparison(ecr(49), fair_rank=42)
    assert comparison is not None
    assert not hasattr(comparison, "rank_gap")
    assert comparison.to_dict()["market_signal_type"] == "ecr"


# --------------------------------------------------------------------------------------
# Each source keeps its own identity and its own arithmetic
# --------------------------------------------------------------------------------------


def test_each_source_is_compared_independently_and_keeps_its_source_id() -> None:
    comparisons = source_comparisons([adp(FFC, 61.0), adp(MFL, 53.0)], fair_rank=42)
    assert set(comparisons) == {FFC, MFL}
    for source_id, comparison in comparisons.items():
        assert comparison.to_dict()["source_id"] == source_id


def test_the_gap_arithmetic_is_a0_unchanged() -> None:
    """Phase 10 adds sources, not a new formula (ADR-040 stays frozen)."""
    comparison = source_comparison(adp(FFC, 61.0), fair_rank=42)
    assert comparison is not None
    assert comparison.rank_gap == rank_gap(61.0, 42)
    assert comparison.regional_value_gap == regional_value_gap(61.0, 42)
    assert comparison.regional_value_gap == pytest.approx(math.log(61.0 / 42), abs=1e-6)


def test_source_specific_dispersion_fields_survive_the_comparison() -> None:
    """FFC has a standard deviation, MFL has min/max, and neither borrows the other's."""
    comparisons = source_comparisons(
        [
            adp(
                FFC, 61.0, adp_sd=8.2, aggregation_window_type="rolling", aggregation_window_days=7
            ),
            adp(
                MFL, 53.0, adp_low=40.0, adp_high=70.0, aggregation_window_type="season_cumulative"
            ),
        ],
        fair_rank=42,
    )
    ffc = comparisons[FFC].to_dict()
    mfl = comparisons[MFL].to_dict()
    assert ffc["market_adp_sd"] == 8.2 and ffc["market_adp_low"] is None
    assert mfl["market_adp_sd"] is None and mfl["market_adp_low"] == 40.0
    assert ffc["aggregation_window_type"] == "rolling" and ffc["aggregation_window_days"] == 7
    assert mfl["aggregation_window_type"] == "season_cumulative"


def test_an_unclaimable_league_size_stays_null() -> None:
    comparison = source_comparison(adp(FFC, 61.0, league_size=None), fair_rank=42)
    assert comparison is not None
    assert comparison.to_dict()["league_size"] is None


# --------------------------------------------------------------------------------------
# The cross-market summary
# --------------------------------------------------------------------------------------


def test_disagreement_range_is_the_spread_between_the_extreme_prices() -> None:
    summary = cross_market_summary(
        [adp(FFC, 61.0), adp(MFL, 53.0), adp("fantasypros_adp", 57.0)],
        player_id="gsis:1",
    )
    assert summary.market_adp_min == 53.0
    assert summary.market_adp_max == 61.0
    assert summary.market_adp_median == 57.0
    assert summary.market_disagreement_range == 8.0


def test_cheapest_means_the_market_where_he_costs_the_latest_pick() -> None:
    """The naming a reader gets wrong at a glance, so it is asserted rather than assumed."""
    summary = cross_market_summary([adp(FFC, 61.0), adp(MFL, 53.0)], player_id="gsis:1")
    assert summary.cheapest_market_source == FFC, "the larger ADP is the later, cheaper pick"
    assert summary.most_expensive_market_source == MFL


def test_the_median_of_an_even_number_of_prices_is_the_midpoint() -> None:
    summary = cross_market_summary([adp(FFC, 60.0), adp(MFL, 50.0)], player_id="gsis:1")
    assert summary.market_adp_median == 55.0


def test_a_single_source_has_a_zero_disagreement_range() -> None:
    summary = cross_market_summary([adp(FFC, 61.0)], player_id="gsis:1")
    assert summary.sources_available == (FFC,)
    assert summary.market_disagreement_range == 0.0
    assert summary.market_adp_median == 61.0


def test_the_summary_is_deterministic_under_input_permutation() -> None:
    quotes = [adp(FFC, 61.0), adp(MFL, 53.0), adp("fantasypros_adp", 61.0)]
    assert (
        cross_market_summary(quotes, player_id="gsis:1").to_dict()
        == cross_market_summary(list(reversed(quotes)), player_id="gsis:1").to_dict()
    )


def test_a_tied_price_resolves_the_cheapest_source_deterministically() -> None:
    tied = [adp(MFL, 61.0), adp(FFC, 61.0)]
    first = cross_market_summary(tied, player_id="gsis:1")
    second = cross_market_summary(list(reversed(tied)), player_id="gsis:1")
    assert first.cheapest_market_source == second.cheapest_market_source


def test_a_nonpositive_price_is_not_a_price() -> None:
    summary = cross_market_summary([adp(FFC, 0.0), adp(MFL, 53.0)], player_id="gsis:1")
    assert summary.sources_available == (MFL,)
    assert source_comparison(adp(FFC, 0.0), fair_rank=42) is None


def test_a_fair_rank_below_one_is_refused_rather_than_producing_a_nan() -> None:
    with pytest.raises(ValueError):
        source_comparison(adp(FFC, 61.0), fair_rank=0)
    with pytest.raises(ValueError):
        ecr_comparison(ecr(49), fair_rank=0)


def test_the_method_version_travels_with_the_layer() -> None:
    assert COMPARISON_METHOD_VERSION.startswith("phase10_")


# --------------------------------------------------------------------------------------
# Building quotes from a retained snapshot
# --------------------------------------------------------------------------------------


def test_only_resolved_rows_for_the_requested_preset_become_quotes() -> None:
    rows = [
        {
            "source_id": FFC,
            "player_id": "gsis:1",
            "scoring_preset": "HALF",
            "market_signal_type": "adp",
            "average_pick": 61.0,
            "adp_sd": 8.2,
            "cohort_id": "ffc-half-ppr",
        },
        {
            "source_id": FFC,
            "player_id": None,
            "scoring_preset": "HALF",
            "market_signal_type": "adp",
            "average_pick": 70.0,
        },
        {
            "source_id": FFC,
            "player_id": "gsis:2",
            "scoring_preset": "PPR",
            "market_signal_type": "adp",
            "average_pick": 44.0,
        },
    ]
    quotes = quotes_from_snapshot_rows(
        rows, scoring_preset="HALF", snapshot_at_utc="2026-09-02T00:00:00Z"
    )
    assert set(quotes) == {"gsis:1"}
    assert quotes["gsis:1"].adp_sd == 8.2
    assert quotes["gsis:1"].snapshot_at_utc == "2026-09-02T00:00:00Z"


def test_an_ecr_snapshot_row_becomes_an_ecr_quote() -> None:
    rows = [
        {
            "source_id": FP,
            "player_id": "gsis:1",
            "scoring_preset": "HALF",
            "market_signal_type": "ecr",
            "average_pick": None,
            "market_rank": 4,
            "consensus_rank_sd": 1.4,
            "sample_size": 104,
        },
    ]
    quotes = quotes_from_snapshot_rows(rows, scoring_preset="HALF", snapshot_at_utc="x")
    quote = quotes["gsis:1"]
    assert quote.is_ecr and not quote.is_adp
    assert quote.market_adp is None
    assert cross_market_summary([quote], player_id="gsis:1").sources_available == ()
