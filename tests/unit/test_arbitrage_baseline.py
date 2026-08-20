"""A0, the deterministic arbitrage baseline (ADR-040).

Everything about A0 is meant to be checkable by hand, and these tests check it by hand. The
sign convention gets its own test at every interesting value, because a flipped sign would
not crash anything — it would quietly tell a drafter to reach for players the model thinks
are expensive, which is the single worst failure this product can have.
"""

from __future__ import annotations

import math

import pytest

from ffdraft.arbitrage.baseline import (
    SCORE_MAXIMUM,
    SCORE_MINIMUM,
    rank_gap,
    regional_value_gap,
    score_block,
    signals_for_block,
)
from ffdraft.arbitrage.frozen import (
    ARBITRAGE_METHOD_VERSION,
    ARBITRAGE_ML_HISTORICAL_FEASIBLE,
    ARBITRAGE_MODE,
    ARBITRAGE_REVISIT_SNAPSHOT_SEASONS,
    FAIR_RANK_STATISTIC,
)

# --------------------------------------------------------------------------------------
# rank_gap: the sign convention
# --------------------------------------------------------------------------------------


def test_a_player_the_market_takes_later_than_the_model_is_a_bargain():
    """`docs/DATA_CONTRACTS.md` 10: positive = model would take him earlier."""
    assert rank_gap(market_adp=30.0, fair_rank=12) == 18.0


def test_agreement_is_zero():
    assert rank_gap(market_adp=12.0, fair_rank=12) == 0.0


def test_a_player_the_market_reaches_for_is_negative():
    assert rank_gap(market_adp=8.0, fair_rank=25) == -17.0


@pytest.mark.parametrize(
    ("adp", "fair", "expected_sign"),
    [(2.4, 1, 1), (1.0, 1, 0), (1.0, 5, -1), (218.0, 300, -1), (300.0, 218, 1)],
)
def test_the_sign_convention_holds_across_the_board(adp, fair, expected_sign):
    gap = rank_gap(adp, fair)
    regional = regional_value_gap(adp, fair)
    assert (gap > 0) == (expected_sign > 0)
    assert (gap < 0) == (expected_sign < 0)
    # The two quantities must never disagree about direction: they are the same comparison.
    assert math.copysign(1, gap) == math.copysign(1, regional) or gap == 0 == regional


# --------------------------------------------------------------------------------------
# regional_value_gap
# --------------------------------------------------------------------------------------


def test_the_regional_gap_is_the_log_ratio():
    # Published to six decimals: finer would imply a precision the market cannot resolve.
    assert regional_value_gap(24.0, 12) == pytest.approx(math.log(2.0), abs=5e-7)
    assert regional_value_gap(12.0, 12) == 0.0
    assert regional_value_gap(6.0, 12) == pytest.approx(math.log(0.5), abs=5e-7)


def test_the_same_pick_gap_matters_more_near_the_top_of_the_draft():
    """This is the whole reason the normalization exists (ADR-040)."""
    early = regional_value_gap(market_adp=11.0, fair_rank=3)
    late = regional_value_gap(market_adp=188.0, fair_rank=180)
    assert rank_gap(11.0, 3) == rank_gap(188.0, 180) == 8.0
    assert early > late


def test_it_is_monotone_in_market_adp_for_a_fixed_fair_rank():
    gaps = [regional_value_gap(adp, 20) for adp in (5.0, 10.0, 20.0, 40.0, 80.0)]
    assert gaps == sorted(gaps)


@pytest.mark.parametrize(("adp", "fair"), [(0.0, 10), (-1.0, 10), (10.0, 0), (10.0, -3)])
def test_an_impossible_input_raises_rather_than_publishing_a_nan(adp, fair):
    with pytest.raises(ValueError, match="market_adp > 0"):
        regional_value_gap(adp, fair)


# --------------------------------------------------------------------------------------
# The score
# --------------------------------------------------------------------------------------


def test_the_score_orders_the_block_and_stays_in_bounds():
    scores = score_block({"a": -1.0, "b": 0.0, "c": 2.0})
    assert scores["c"] > scores["b"] > scores["a"]
    assert all(SCORE_MINIMUM <= value <= SCORE_MAXIMUM for value in scores.values())
    assert scores == {"a": 16.67, "b": 50.0, "c": 83.33}


def test_ties_share_the_mean_of_their_midpoints():
    """Two identical gaps must score identically, whatever order they arrived in."""
    scores = score_block({"a": 1.0, "b": 1.0, "c": 5.0})
    assert scores["a"] == scores["b"] == pytest.approx(33.33, abs=0.01)
    assert scores["c"] == pytest.approx(83.33, abs=0.01)


def test_a_single_row_block_scores_the_honest_midpoint():
    """One element is not "the biggest bargain on the board"; it is the only element."""
    assert score_block({"only": 4.0}) == {"only": 50.0}


def test_an_empty_block_scores_nothing():
    assert score_block({}) == {}


def test_the_score_is_invariant_to_input_order():
    forward = score_block({"a": 1.0, "b": 3.0, "c": 2.0})
    backward = score_block({"c": 2.0, "b": 3.0, "a": 1.0})
    assert forward == backward


def test_the_score_depends_only_on_the_ordering_not_the_magnitudes():
    """A percentile, deliberately: the gap's scale depends on how deep the market runs."""
    assert score_block({"a": 1.0, "b": 2.0, "c": 3.0}) == score_block(
        {"a": 1.0, "b": 100.0, "c": 1000.0},
    )


# --------------------------------------------------------------------------------------
# Block assembly
# --------------------------------------------------------------------------------------


def test_signals_carry_all_three_quantities():
    signals = signals_for_block(
        [("gsis:1", 1, 2.4), ("gsis:2", 12, 30.0), ("gsis:3", 25, 8.0)],
    )
    assert set(signals) == {"gsis:1", "gsis:2", "gsis:3"}
    assert signals["gsis:2"].rank_gap == 18.0
    assert signals["gsis:2"].regional_value_gap == pytest.approx(math.log(30.0 / 12), abs=5e-7)
    assert signals["gsis:3"].rank_gap == -17.0
    assert signals["gsis:3"].arbitrage_score < signals["gsis:2"].arbitrage_score


def test_blocks_are_scored_independently():
    """A 10-team board and a 14-team board price different scarcity."""
    small = signals_for_block([("a", 1, 10.0), ("b", 2, 4.0)])
    large = signals_for_block([("a", 1, 10.0), ("b", 2, 4.0), ("c", 3, 3.0)])
    assert small["a"].arbitrage_score == 75.0
    assert large["a"].arbitrage_score == pytest.approx(83.33, abs=0.01)
    assert small["a"].rank_gap == large["a"].rank_gap


# --------------------------------------------------------------------------------------
# The freeze
# --------------------------------------------------------------------------------------


def test_v1_is_baseline_mode_and_says_why():
    """ADR-010 is source evidence, not a preference. Nothing here may flip it quietly."""
    assert str(ARBITRAGE_MODE) == "baseline"
    assert ARBITRAGE_ML_HISTORICAL_FEASIBLE is False
    assert ARBITRAGE_REVISIT_SNAPSHOT_SEASONS == 3
    assert ARBITRAGE_METHOD_VERSION == "a0_rank_gap_v1"


def test_a0_consumes_fair_rank_and_not_a_tier_boundary():
    """ADR-035/ADR-040: tier boundaries failed their stability gate; fair rank did not."""
    assert FAIR_RANK_STATISTIC == "median_vorp"
    source = (__import__("inspect").getsource(signals_for_block)).lower()
    assert "tier" not in source
