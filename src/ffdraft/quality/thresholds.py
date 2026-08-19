"""Launch data-quality thresholds.

The numbers in `docs/DATA_CONTRACTS.md` section 12 live here so a production pipeline and
its tests read the same constant, and so tuning one - which that section says must be
evidence-driven - is a single visible edit rather than a scatter of literals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

__all__ = [
    "HistoricalThresholds",
    "HISTORICAL_AGE_COVERAGE_MINIMUM",
    "HISTORICAL_CANONICAL_KEY_MINIMUM",
    "HISTORICAL_DUPLICATE_KEY_MAXIMUM",
    "HISTORICAL_EXPECTED_POINTS_MINIMUM",
    "HISTORICAL_LABEL_COVERAGE_MINIMUM",
    "HISTORICAL_ROW_COUNT_TOLERANCE",
    "HISTORICAL_SNAP_BRIDGE_MINIMUM",
    "IDENTITY_COVERAGE_MINIMUM",
    "MARKET_SOURCE_MAX_AGE",
    "NFLVERSE_SOURCE_MAX_AGE",
    "TOP_OVERALL_COVERAGE_MINIMUM",
    "TOP_OVERALL_RANKS",
]

#: >= 95% of current model-eligible QB/RB/WR/TE players must resolve canonically.
IDENTITY_COVERAGE_MINIMUM = 0.95

#: 100% of players in the public top-150 overall output must resolve canonically.
TOP_OVERALL_RANKS = 150
TOP_OVERALL_COVERAGE_MINIMUM = 1.0

#: Freshness budgets (`docs/OPERATIONS.md` section 9). Market data refreshes daily; the
#: nflverse feeds are allowed a longer window because they publish on a slower cadence.
MARKET_SOURCE_MAX_AGE = timedelta(days=2)
NFLVERSE_SOURCE_MAX_AGE = timedelta(days=4)


# --------------------------------------------------------------------------------------
# Phase-2 historical dataset thresholds
# --------------------------------------------------------------------------------------
#
# Each of these is set from a *measurement* plus deliberate headroom, never from "what the
# current dataset happens to score". The measured value and the reason for the margin are
# recorded next to the constant, and the quality report prints observed-versus-threshold so
# a future tightening is an informed edit rather than a guess.

#: Every eligible historical row must carry a canonical namespaced ``player_id``. The
#: preseason universe is assembled exclusively from GSIS-keyed sources, so anything below
#: 1.0 is a construction bug rather than a coverage shortfall. Measured: 1.0.
HISTORICAL_CANONICAL_KEY_MINIMUM = 1.0

#: Duplicate ``(season, player_id)`` keys allowed in the feature table. The Phase-2 exit
#: gate names zero explicitly.
HISTORICAL_DUPLICATE_KEY_MAXIMUM = 0

#: Share of rows carrying an age at the anchor. Measured 0.967 over 2014-2025, with the
#: worst season (2019) at 0.925. The missing rows are not a join failure: they are 380 deep
#: fringe roster entries - practice-squad receivers and backs - for whom neither the player
#: master nor any season roster publishes a birth date, and they cluster in the seasons
#: after nflverse widened roster coverage in 2016. The threshold sits below the observed
#: overall rate with real headroom so a genuine collapse in birth-date publication still
#: trips it, while the report's per-season and per-position coverage tables surface drift
#: long before the gate does.
HISTORICAL_AGE_COVERAGE_MINIMUM = 0.93

#: Share of rows *with previous-season statistics* whose previous-season snap counts
#: resolved through the ``pfr_id`` bridge. This is a genuine cross-id-space join and is the
#: identity metric worth a gate: the canonical key itself cannot fail. The margin is wide
#: enough to absorb an early season with sparser PFR ids without hiding a broken bridge.
HISTORICAL_SNAP_BRIDGE_MINIMUM = 0.90

#: Share of rows with previous-season statistics that also resolved to ffopportunity rows.
#: ffopportunity models only plays it can attribute, so a player with a stat line and no
#: expected-points row is normal; a large drop would mean the join, not the coverage, broke.
HISTORICAL_EXPECTED_POINTS_MINIMUM = 0.80

#: Every eligible row must receive a fantasy label under every scoring preset, and a VORP
#: label under every requested league preset. A missing label is a join failure.
HISTORICAL_LABEL_COVERAGE_MINIMUM = 1.0

#: Season-over-season row-count tolerance for the eligible universe, relative to the median
#: season. Wide enough to accommodate a genuine era change (the 2025 snapshot era adds
#: undrafted rookies the earlier universes cannot see) and narrow enough to catch a season
#: whose source returned a fraction of its rows.
HISTORICAL_ROW_COUNT_TOLERANCE = 0.35


@dataclass(frozen=True, slots=True)
class HistoricalThresholds:
    """The Phase-2 gate thresholds, as one object a build can pass around.

    Production values come from measurements on the real 2014-2025 dataset. The fixture
    variant exists because applying a production coverage threshold to a deliberately
    adversarial thirty-row fixture is a category error, not a relaxation of the standard -
    the same reasoning Phase 1 recorded for ``FIXTURE_IDENTITY_COVERAGE_MINIMUM``. A test
    asserts the fixture values are strictly looser than production and that production is
    unchanged, so the two can never quietly converge.
    """

    canonical_key_minimum: float = HISTORICAL_CANONICAL_KEY_MINIMUM
    duplicate_key_maximum: int = HISTORICAL_DUPLICATE_KEY_MAXIMUM
    age_coverage_minimum: float = HISTORICAL_AGE_COVERAGE_MINIMUM
    snap_bridge_minimum: float = HISTORICAL_SNAP_BRIDGE_MINIMUM
    expected_points_minimum: float = HISTORICAL_EXPECTED_POINTS_MINIMUM
    label_coverage_minimum: float = HISTORICAL_LABEL_COVERAGE_MINIMUM
    row_count_tolerance: float = HISTORICAL_ROW_COUNT_TOLERANCE
    profile: str = "production"

    @classmethod
    def production(cls) -> HistoricalThresholds:
        return cls()

    @classmethod
    def fixture(cls) -> HistoricalThresholds:
        """Thresholds for the synthetic historical fixtures.

        The fixture deliberately contains a player for whom no source publishes a birth
        date, and it is small enough that one such player is 7% of the rows. Two seasons
        also cannot produce a meaningful row-count median, so that tolerance is widened out
        of the way rather than left to fire on noise.
        """
        return cls(
            age_coverage_minimum=0.80,
            expected_points_minimum=0.50,
            row_count_tolerance=1.0,
            profile="fixture",
        )
