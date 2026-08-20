"""The Phase-5 arbitrage freeze: every version and bound in one screen.

Same discipline as `ffdraft.modeling.frozen`. Each constant here is the outcome of a
decision recorded in an ADR, written and committed **before** the 2026 arbitrage board it
decides was produced. Nothing here may change in response to which players the board likes.

Reading order for anyone auditing an arbitrage build:

* ADR-010 — why V1 is baseline-only and what would let that change;
* ADR-039 — the cohort sufficiency rule and its selection policy;
* ADR-040 — the A0 formula, sign convention and score semantics;
* ADR-041 — what `confidence` means, and why dispersion does not move it;
* ADR-042 — the trend definition and its history requirement.
"""

from __future__ import annotations

from ffdraft.contracts.enums import ArbitrageMode
from ffdraft.market.cohorts import COHORT_RULE_VERSION
from ffdraft.market.trend import TREND_RULE_VERSION

__all__ = [
    "ARBITRAGE_COHORT_RULE_VERSION",
    "ARBITRAGE_CONFIDENCE_VERSION",
    "ARBITRAGE_METHOD_VERSION",
    "ARBITRAGE_MODE",
    "ARBITRAGE_ML_HISTORICAL_FEASIBLE",
    "ARBITRAGE_REVISIT_SNAPSHOT_SEASONS",
    "ARBITRAGE_TREND_VERSION",
    "FAIR_RANK_STATISTIC",
]

#: The A0 baseline's method version. A change to the formula is a new version, not an edit.
ARBITRAGE_METHOD_VERSION = "a0_rank_gap_v1"

#: The confidence rubric's version (ADR-041).
ARBITRAGE_CONFIDENCE_VERSION = "phase5_confidence_v1"

#: Re-exported so a card or a build records one consistent set of versions.
ARBITRAGE_COHORT_RULE_VERSION = COHORT_RULE_VERSION
ARBITRAGE_TREND_VERSION = TREND_RULE_VERSION

#: ADR-010, on measured source evidence: MFL's historical export is a season-long aggregate
#: recomputed at request time, so a historical "market cost" includes drafts held after the
#: season's outcomes were partly known. V1 therefore trains nothing.
ARBITRAGE_ML_HISTORICAL_FEASIBLE = False
ARBITRAGE_MODE = ArbitrageMode.BASELINE

#: How many draft seasons of *our own* point-in-time snapshots must exist before a learned
#: arbitrage model can be attempted with an honest out-of-time promotion gate (ADR-010).
ARBITRAGE_REVISIT_SNAPSHOT_SEASONS = 3

#: The intrinsic quantity A0 consumes. Median simulated VORP produced this ranking
#: (ADR-034); tier ordinals and tier edges are deliberately **not** inputs, because the
#: tier stability gate failed and fair rank did not (ADR-035, ADR-040).
FAIR_RANK_STATISTIC = "median_vorp"
