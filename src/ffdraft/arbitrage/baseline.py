"""A0: the deterministic fair-rank-versus-ADP arbitrage baseline (ADR-040).

**Boundary module.** Arbitrage consumes intrinsic outputs and market data; nothing here may
ever be imported by an intrinsic feature, label, model or simulation module.

Three quantities, in increasing distance from the raw evidence:

``rank_gap = market_adp - fair_rank``
    The interpretable one. Positive means the model would take the player earlier than the
    market does — a bargain. Published on every row and never replaced by a derived score.

``regional_value_gap = ln(market_adp / fair_rank)``
    The same comparison made comparable across draft regions. Eight picks between fair rank
    3 and ADP 11 is a round of value; eight picks between 180 and 188 is noise. A ratio says
    that directly and has no fitted parameter. Zero is agreement, positive is a bargain.

``arbitrage_score``
    The midpoint percentile of ``regional_value_gap`` inside one (league preset, scoring
    preset) block, on 0-100. An *ordering*, not a magnitude.

There is deliberately no reliability multiplier. Data quality reaches the reader through
``confidence`` and ``quality_flags`` and nowhere else, so a reader can sort by signal and
filter by quality independently (ADR-041).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "SCORE_MAXIMUM",
    "SCORE_MINIMUM",
    "BaselineSignal",
    "rank_gap",
    "regional_value_gap",
    "score_block",
    "signals_for_block",
]

SCORE_MINIMUM = 0.0
SCORE_MAXIMUM = 100.0

#: Published precision. Two decimals on a pick-denominated gap is already finer than the
#: market can resolve; more would imply a precision the source does not have.
_GAP_PRECISION = 2
_LOG_PRECISION = 6
_SCORE_PRECISION = 2


def rank_gap(market_adp: float, fair_rank: int) -> float:
    """``market_adp - fair_rank``. Positive = bargain (ADR-040, `docs/DATA_CONTRACTS.md` 10)."""
    return round(float(market_adp) - float(fair_rank), _GAP_PRECISION)


def regional_value_gap(market_adp: float, fair_rank: int) -> float:
    """``ln(market_adp / fair_rank)``: the gap normalized for draft region.

    Both arguments are positive by contract — ``market_adp > 0`` is a schema constraint and
    ``fair_rank >= 1`` is an artifact invariant — so the logarithm is always finite. A
    caller that manages to violate either gets a ``ValueError`` rather than a NaN in a
    published artifact.
    """
    if market_adp <= 0 or fair_rank < 1:
        raise ValueError(
            f"regional_value_gap needs market_adp > 0 and fair_rank >= 1; "
            f"got {market_adp!r} and {fair_rank!r}",
        )
    return round(math.log(float(market_adp) / float(fair_rank)), _LOG_PRECISION)


@dataclass(frozen=True, slots=True)
class BaselineSignal:
    """A0's three quantities for one player in one preset block."""

    player_id: str
    fair_rank: int
    market_adp: float
    rank_gap: float
    regional_value_gap: float
    arbitrage_score: float


def score_block(gaps: Mapping[str, float]) -> dict[str, float]:
    """Midpoint percentiles of ``regional_value_gap`` within one preset block.

    Deterministic in every respect a caller could notice:

    * ordering is by ``(gap, player_id)``, so an input permutation cannot change a score;
    * ties receive the **mean** of their group's midpoint percentiles, so two identical
      gaps always score identically and the block's total is unaffected;
    * an empty block scores nothing, and a single-row block scores 50.0 — the honest
      midpoint of an ordering with one element, not 100.
    """
    if not gaps:
        return {}
    ordered = sorted(gaps.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    midpoints = [SCORE_MAXIMUM * (index + 0.5) / count for index in range(count)]

    scores: dict[str, float] = {}
    index = 0
    while index < count:
        end = index + 1
        while end < count and ordered[end][1] == ordered[index][1]:
            end += 1
        shared = sum(midpoints[index:end]) / (end - index)
        for position in range(index, end):
            scores[ordered[position][0]] = round(shared, _SCORE_PRECISION)
        index = end
    return scores


def signals_for_block(
    rows: Sequence[tuple[str, int, float]],
) -> dict[str, BaselineSignal]:
    """A0 over one (league preset, scoring preset) block.

    ``rows`` is ``(player_id, fair_rank, market_adp)``. Blocks are scored independently
    because a percentile only means something inside the population it ranks: a 10-team
    board and a 14-team board price different scarcity, and mixing them would make the
    score a statement about which preset a row came from.
    """
    gaps = {
        player_id: regional_value_gap(market_adp, fair_rank)
        for player_id, fair_rank, market_adp in rows
    }
    scores = score_block(gaps)
    return {
        player_id: BaselineSignal(
            player_id=player_id,
            fair_rank=fair_rank,
            market_adp=market_adp,
            rank_gap=rank_gap(market_adp, fair_rank),
            regional_value_gap=gaps[player_id],
            arbitrage_score=scores[player_id],
        )
        for player_id, fair_rank, market_adp in rows
    }
