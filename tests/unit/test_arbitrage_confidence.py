"""The arbitrage confidence rubric (ADR-041).

`confidence` is the field most likely to be misread, because in every other product a
confidence is a probability. Here it is a statement about market-data quality, and there is
no fitted model behind it at all. These tests pin each clause, pin the order they are
evaluated in, and pin the one thing the rubric deliberately does *not* use.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ffdraft.arbitrage.confidence import CONFIDENCE_RUBRIC, assess
from ffdraft.contracts.enums import Confidence
from ffdraft.market.current import MarketPrice
from ffdraft.timeutil import parse_utc

SNAPSHOT = parse_utc("2026-08-20T12:00:00Z")


def price(**overrides) -> MarketPrice:
    """A comfortably `high` price, with clauses knocked out per test."""
    defaults: dict[str, object] = {
        "player_id": "gsis:00-0000002",
        "scoring_preset": "PPR",
        "league_size": 12,
        "market_adp": 24.0,
        "market_rank": 20,
        "sample_size": 350,
        "adp_low": 12.0,
        "adp_high": 44.0,
        "adp_sd": None,
        "source_id": "myfantasyleague_adp",
        "cohort_id": "ppr-fcount12",
        "cohort_detail": "FCOUNT=12&IS_PPR=1 (exact cohort)",
        "cohort_exact": True,
        "cohort_sufficient": True,
        "snapshot_at_utc": SNAPSHOT,
        "snapshot_stale": False,
        "secondary_bridge_only": False,
        "market_trend": None,
        "trend_flags": ("insufficient_trend_history",),
        "quality_flags": (),
    }
    defaults.update(overrides)
    return MarketPrice(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The bands
# --------------------------------------------------------------------------------------


def test_an_exact_well_sampled_fresh_price_is_high():
    verdict = assess(price())
    assert verdict.confidence is Confidence.HIGH
    assert any("exact cohort" in reason for reason in verdict.reasons)


def test_no_sample_size_is_unknown_not_low():
    """ "We do not know" and "we know it is thin" are different statements."""
    verdict = assess(price(sample_size=None))
    assert verdict.confidence is Confidence.UNKNOWN
    assert verdict.reasons == ("no market sample size published for this player",)


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"cohort_sufficient": False}, "failed the sufficiency rule"),
        ({"sample_size": 29}, "draft(s) priced this player"),
        ({"secondary_bridge_only": True}, "secondary bridge"),
        ({"snapshot_stale": True}, "older than the freshness budget"),
    ],
)
def test_each_low_clause_fires_on_its_own(override, fragment):
    verdict = assess(price(**override))
    assert verdict.confidence is Confidence.LOW
    assert any(fragment in reason for reason in verdict.reasons)


def test_every_low_clause_that_fired_is_reported():
    """Phase 6 has to be able to explain a low-confidence row, not just label it."""
    verdict = assess(
        price(
            cohort_sufficient=False, sample_size=4, secondary_bridge_only=True, snapshot_stale=True
        ),
    )
    assert verdict.confidence is Confidence.LOW
    assert len(verdict.reasons) == 4


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"cohort_exact": False}, "is approximate for"),
        ({"sample_size": 199}, "draft(s) priced this player"),
    ],
)
def test_a_price_short_of_high_but_clear_of_low_is_medium(override, fragment):
    verdict = assess(price(**override))
    assert verdict.confidence is Confidence.MEDIUM
    assert any(fragment in reason for reason in verdict.reasons)


def test_low_is_evaluated_before_high():
    """An exact, huge-sample cohort that failed sufficiency is still low."""
    verdict = assess(price(cohort_sufficient=False, sample_size=5000))
    assert verdict.confidence is Confidence.LOW


def test_half_ppr_can_never_reach_high():
    """It is the source's limitation stated plainly, not smoothed over (ADR-039)."""
    verdict = assess(price(scoring_preset="HALF", cohort_exact=False, cohort_id="ppr"))
    assert verdict.confidence is Confidence.MEDIUM


# --------------------------------------------------------------------------------------
# What the rubric deliberately ignores
# --------------------------------------------------------------------------------------


def test_dispersion_does_not_move_the_tier():
    """minPick/maxPick widen with sample size, so they are not comparable across rows.

    Using them would systematically punish the best-sampled players, which is the opposite
    of what a confidence field should do.
    """
    tight = assess(price(adp_low=23.0, adp_high=25.0))
    wide = assess(price(adp_low=1.0, adp_high=200.0))
    assert tight.confidence is wide.confidence is Confidence.HIGH
    assert CONFIDENCE_RUBRIC.to_dict()["dispersion_excluded_because"]


def test_trend_availability_does_not_move_the_tier():
    """Trend is a separate question from whether today's price can be trusted."""
    without = assess(price(market_trend=None, trend_flags=("insufficient_trend_history",)))
    with_trend = assess(price(market_trend=1.4, trend_flags=()))
    assert without.confidence is with_trend.confidence


def test_the_rubric_declares_that_it_is_not_a_probability():
    described = CONFIDENCE_RUBRIC.to_dict()
    assert described["rubric_version"] == "phase5_confidence_v1"
    assert "not a probability" in described["meaning"]


def test_the_rubric_is_deterministic():
    subject = price(sample_size=64, cohort_exact=False)
    assert assess(subject) == assess(subject)


def test_range_rounds_is_available_for_description():
    """Published and flagged, just not scored."""
    assert price(adp_low=12.0, adp_high=84.0).range_rounds == pytest.approx(6.0)
    assert price(adp_low=None).range_rounds is None


def test_freshness_uses_the_documented_budget():
    from ffdraft.quality.thresholds import MARKET_SOURCE_MAX_AGE

    assert timedelta(days=2) == MARKET_SOURCE_MAX_AGE
