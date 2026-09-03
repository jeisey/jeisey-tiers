"""Deterministic arbitrage: the A0 baseline, its confidence rubric and its build.

**This package is downstream of everything intrinsic and downstream of the market layer.**
Information flows intrinsic -> market -> arbitrage and never the other way (`AGENTS.md`
section 1); ``tests/contract/test_architecture_boundary.py`` walks the import graph and
asserts it.

V1 is `arbitrage_mode = baseline` and will stay so until at least three draft seasons of our
own point-in-time snapshots exist (ADR-010, ADR-038).

**The facade deliberately stops short of** :mod:`ffdraft.arbitrage.build`. The module graph
is acyclic — :mod:`ffdraft.arbitrage.baseline` is a leaf with no first-party imports,
:mod:`ffdraft.market.comparison` reuses its frozen A0 arithmetic rather than restating the
formula (ADR-040, ADR-065), and ``build`` is the composition layer above both. Re-exporting
the composition layer from the package root is what would make it a cycle: importing the
leaf runs this file, which would drag ``build`` in, which imports the market layer that is
still part-way through importing the leaf. Both pipelines already import
``ffdraft.arbitrage.build`` directly, which is the honest spelling for a composition module,
so nothing is lost by leaving it out.
"""

from __future__ import annotations

from ffdraft.arbitrage.baseline import (
    BaselineSignal,
    rank_gap,
    regional_value_gap,
    score_block,
    signals_for_block,
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
    "BaselineSignal",
    "ConfidenceRubric",
    "ConfidenceVerdict",
    "rank_gap",
    "regional_value_gap",
    "score_block",
    "signals_for_block",
]
