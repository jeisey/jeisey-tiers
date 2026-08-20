"""Deterministic arbitrage: the A0 baseline, its confidence rubric and its build.

**This package is downstream of everything intrinsic and downstream of the market layer.**
Information flows intrinsic -> market -> arbitrage and never the other way (`AGENTS.md`
section 1); ``tests/contract/test_architecture_boundary.py`` walks the import graph and
asserts it.

V1 is `arbitrage_mode = baseline` and will stay so until at least three draft seasons of our
own point-in-time snapshots exist (ADR-010, ADR-038).
"""

from __future__ import annotations

from ffdraft.arbitrage.baseline import (
    BaselineSignal,
    rank_gap,
    regional_value_gap,
    score_block,
    signals_for_block,
)
from ffdraft.arbitrage.build import (
    ArbitrageBuildResult,
    build_arbitrage_records,
)
from ffdraft.arbitrage.confidence import CONFIDENCE_RUBRIC, ConfidenceRubric, ConfidenceVerdict
from ffdraft.arbitrage.frozen import (
    ARBITRAGE_CONFIDENCE_VERSION,
    ARBITRAGE_METHOD_VERSION,
    ARBITRAGE_ML_HISTORICAL_FEASIBLE,
    ARBITRAGE_MODE,
    ARBITRAGE_REVISIT_SNAPSHOT_SEASONS,
)

__all__ = [
    "ARBITRAGE_CONFIDENCE_VERSION",
    "ARBITRAGE_METHOD_VERSION",
    "ARBITRAGE_ML_HISTORICAL_FEASIBLE",
    "ARBITRAGE_MODE",
    "ARBITRAGE_REVISIT_SNAPSHOT_SEASONS",
    "CONFIDENCE_RUBRIC",
    "ArbitrageBuildResult",
    "BaselineSignal",
    "ConfidenceRubric",
    "ConfidenceVerdict",
    "build_arbitrage_records",
    "rank_gap",
    "regional_value_gap",
    "score_block",
    "signals_for_block",
]
