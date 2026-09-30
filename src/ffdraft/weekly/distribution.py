"""From seven published quantiles to a comparable distribution (``quantile_distribution_v1``).

A start/sit question is a question about two distributions: *how often does he outscore
him*. The artifact publishes seven quantiles per player, and both this module and
``web/src/data/startsit.ts`` turn them into the same thing, by the same rule, so the number
the evaluation scored is the number the page prints:

1. **Knots.** The seven levels, plus a lower knot at probability 0 and an upper knot at 1,
   each a linear extension of the adjacent segment (``TAIL_RULE``: once its width below, twice
   its width above, because weekly points are right-skewed).
2. **Grid.** The inverse CDF is piecewise linear between knots and is read at ``M`` midpoints
   ``u_i = (i + 0.5) / M``. That grid *is* the distribution from here on.
3. **P(A > B).** For every grid point of A, count the grid points of B strictly below it and
   half of those equal to it; divide by ``M²``. Exact for the two discretised distributions,
   deterministic, and needs nothing but a sorted array and a binary search — which is why the
   browser can do it identically.
4. **Win probability.** With a matchup margin ``m ~ Normal(mu, sigma)`` for everything *except*
   the slot being decided, starting a player with grid ``x`` wins with probability
   ``mean_i Phi((mu + x_i) / sigma)``.

Independence is assumed between the two players in (3). The evaluation that promoted the
model scored it that way; a measured same-game correlation is published separately and the
page says when it applies.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from ffdraft.weekly.frozen import PAIRWISE_GRID_POINTS, TAIL_RULE, WEEKLY_QUANTILE_LEVELS

__all__ = [
    "grid_from_quantiles",
    "grids_from_matrix",
    "knots",
    "normal_cdf",
    "pairwise_matrix",
    "prob_greater",
    "prob_greater_grids",
    "win_probability",
]

Floats = NDArray[np.float64]


def knots(
    quantiles: Sequence[float],
    levels: Sequence[float] = WEEKLY_QUANTILE_LEVELS,
) -> tuple[Floats, Floats]:
    """``(probabilities, values)`` including the two tail knots. Values are made monotone."""
    values = np.sort(np.asarray(quantiles, dtype=np.float64))
    if values.shape[0] != len(levels):
        raise ValueError(f"expected {len(levels)} quantiles, got {values.shape[0]}")
    lower = values[0] - float(TAIL_RULE["lower_factor"]) * (values[1] - values[0])
    upper = values[-1] + float(TAIL_RULE["upper_factor"]) * (values[-1] - values[-2])
    taus = np.concatenate(([0.0], np.asarray(levels, dtype=np.float64), [1.0]))
    return taus, np.concatenate(([lower], values, [upper]))


def grid_from_quantiles(
    quantiles: Sequence[float],
    *,
    points: int = PAIRWISE_GRID_POINTS,
    levels: Sequence[float] = WEEKLY_QUANTILE_LEVELS,
) -> Floats:
    """The distribution as ``points`` equally likely values, ascending."""
    taus, values = knots(quantiles, levels)
    grid_u = (np.arange(points, dtype=np.float64) + 0.5) / points
    return np.interp(grid_u, taus, values)


def grids_from_matrix(
    matrix: Floats,
    *,
    points: int = PAIRWISE_GRID_POINTS,
    levels: Sequence[float] = WEEKLY_QUANTILE_LEVELS,
) -> Floats:
    """Row-wise :func:`grid_from_quantiles` for an ``(n, len(levels))`` matrix."""
    return np.vstack([grid_from_quantiles(row, points=points, levels=levels) for row in matrix])


def prob_greater_grids(grid_a: Floats, grid_b: Floats) -> float:
    """P(A > B) for two ascending grids of equal length, ties counted half."""
    below = np.searchsorted(grid_b, grid_a, side="left")
    at_or_below = np.searchsorted(grid_b, grid_a, side="right")
    total = float(np.sum(below) + 0.5 * np.sum(at_or_below - below))
    return total / float(grid_a.shape[0] * grid_b.shape[0])


def prob_greater(
    quantiles_a: Sequence[float],
    quantiles_b: Sequence[float],
    *,
    points: int = PAIRWISE_GRID_POINTS,
) -> float:
    """P(A outscores B), independent, from two published quantile sets."""
    return prob_greater_grids(
        grid_from_quantiles(quantiles_a, points=points),
        grid_from_quantiles(quantiles_b, points=points),
    )


def pairwise_matrix(grids: Floats) -> Floats:
    """``P[i, j] = P(player i outscores player j)`` for every pair in one pool.

    Vectorised over the pool: one binary search per column player against every grid point of
    every row player. The diagonal is 0.5 by construction.
    """
    count, points = grids.shape
    flat = grids.ravel()
    result = np.empty((count, count), dtype=np.float64)
    for j in range(count):
        below = np.searchsorted(grids[j], flat, side="left").reshape(count, points)
        at_or_below = np.searchsorted(grids[j], flat, side="right").reshape(count, points)
        result[:, j] = (below.sum(axis=1) + 0.5 * (at_or_below - below).sum(axis=1)) / (
            points * points
        )
    return result


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def win_probability(grid: Floats, *, margin: float, sigma: float) -> float:
    """P(the matchup is won) when this player fills the slot.

    ``margin`` is the expected margin from every *other* slot (yours minus theirs) and
    ``sigma`` its standard deviation. Averaged over the player's own grid, so a wide
    distribution helps an underdog and hurts a favourite, which is the whole point.
    """
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    scaled = (margin + grid) / (sigma * math.sqrt(2.0))
    return float(np.mean(0.5 * (1.0 + np.vectorize(math.erf)(scaled))))
