"""Launch data-quality thresholds.

The numbers in `docs/DATA_CONTRACTS.md` section 12 live here so a production pipeline and
its tests read the same constant, and so tuning one - which that section says must be
evidence-driven - is a single visible edit rather than a scatter of literals.
"""

from __future__ import annotations

from datetime import timedelta

__all__ = [
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
