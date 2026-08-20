"""Market data: cohorts, point-in-time snapshots, retention, trend and the current price.

**This package is the market side of the intrinsic/market firewall** (`AGENTS.md` section
1, `docs/ARCHITECTURE.md` 3.1). Market data may consume intrinsic outputs — the arbitrage
board is built from the published fair ranking — and the reverse is a design bug. Nothing
under ``ffdraft.features``, ``ffdraft.labels``, ``ffdraft.modeling`` or ``ffdraft.simulation``
may import this package or ``ffdraft.sources.market``, and
``tests/contract/test_architecture_boundary.py`` asserts it by walking the import graph.
"""

from __future__ import annotations

from ffdraft.market.cohorts import (
    CANDIDATE_COHORTS,
    COHORT_RULE_VERSION,
    COHORT_SUFFICIENCY_RULE,
    CohortAssignment,
    CohortMeasurement,
    CohortSufficiency,
    CohortSufficiencyRule,
    cohort_by_id,
    select_cohorts,
    widest_cohort,
)
from ffdraft.market.current import CurrentMarket, MarketPrice, build_current_market
from ffdraft.market.identity import MarketIdentity, load_market_identity
from ffdraft.market.measure import (
    BoardIndex,
    CohortReport,
    board_from_tier_records,
    measure_cohorts,
)
from ffdraft.market.snapshot import (
    MarketSnapshot,
    SnapshotConflictError,
    SnapshotManifest,
    SnapshotStore,
    snapshot_key,
    verify_store,
)
from ffdraft.market.trend import TREND_RULE, TrendResult, compute_trends

__all__ = [
    "CANDIDATE_COHORTS",
    "COHORT_RULE_VERSION",
    "COHORT_SUFFICIENCY_RULE",
    "TREND_RULE",
    "BoardIndex",
    "CohortAssignment",
    "CohortMeasurement",
    "CohortReport",
    "CohortSufficiency",
    "CohortSufficiencyRule",
    "CurrentMarket",
    "MarketIdentity",
    "MarketPrice",
    "MarketSnapshot",
    "SnapshotConflictError",
    "SnapshotManifest",
    "SnapshotStore",
    "TrendResult",
    "board_from_tier_records",
    "build_current_market",
    "cohort_by_id",
    "compute_trends",
    "load_market_identity",
    "measure_cohorts",
    "select_cohorts",
    "snapshot_key",
    "verify_store",
    "widest_cohort",
]
