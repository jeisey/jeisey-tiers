"""The documented alternative segmentation: exact dynamic programming on quantile distance.

`docs/MODELING.md` section 14.3 names this as the fallback if the PELT candidate proves
unstable or unintuitive under measured tests, and ADR-030's stability rule says the same:
if PELT fails, the response is *this*, not a wider penalty search.

The two algorithms optimize different things, which is the whole reason the alternative
exists. ``ruptures.Pelt(model="rbf")`` finds points where the *kernel mean* of the feature
vector changes - a shift in level or in spread, detected through a Gaussian kernel. This one
minimizes **within-tier distributional distance** directly:

    total cost = sum over tiers of ( within-tier sum of squared quantile distance )
                 + penalty x (number of tiers)

A player's distribution is represented by its quantile vector, and the L2 distance between
two quantile functions on a common level grid is the 2-Wasserstein distance between the
distributions they describe. So minimizing within-tier squared quantile distance is
minimizing within-tier Wasserstein dispersion, which is exactly the phrase section 14.3 uses.

Three implementation choices worth stating:

* **Exact, not heuristic.** Contiguous segmentation with an additive per-segment cost is a
  shortest-path problem, solved exactly by dynamic programming in O(n^2) with prefix sums.
  At a 300-player board that is instant, and it removes "the search found a local optimum"
  from the list of things a boundary could be an artifact of.
* **Three quantiles, not four features.** The quantile-function representation is P25, P50
  and P75. The PELT candidate also passes the interquartile spread, which under an L2 cost
  would double-count dispersion, since the spread *is* P75 - P25.
* **Cost normalized per feature.** Segment cost is divided by the number of features, so a
  penalty means roughly the same thing here as under the RBF cost - both then sit at
  O(board size) when the board is one tier. The frozen penalty grid is a set of numbers; this
  normalization is what makes those numbers comparable across the two algorithms, and it is
  declared here rather than chosen after seeing which grid values worked.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.tiers.segmentation import (
    BoundaryDiagnostic,
    Segmentation,
    _probability_lower_exceeds_upper,
    adjacent_effect_sizes,
    standardize,
)

__all__ = ["DP_SEGMENTATION_VERSION", "QUANTILE_FEATURE_COLUMNS", "segment_board_dp"]

Floats = NDArray[np.float64]

DP_SEGMENTATION_VERSION = "dp_quantile_wasserstein_v1"

#: The quantile-function representation. Spread is deliberately absent: it is P75 - P25 and
#: would be counted twice under an L2 cost.
QUANTILE_FEATURE_COLUMNS: tuple[str, ...] = ("p25_vorp", "p50_vorp", "p75_vorp")


def _segment_costs(matrix: Floats) -> Floats:
    """``cost[i, j]`` = within-segment sum of squares for rows ``i..j-1``, per feature.

    Prefix sums make every segment's cost O(1): the sum of squared distances to a segment's
    mean is ``sum(x^2) - (sum x)^2 / L``, computed per feature and averaged over features.
    """
    n, d = matrix.shape
    prefix = np.zeros((n + 1, d), dtype=np.float64)
    prefix_square = np.zeros((n + 1, d), dtype=np.float64)
    prefix[1:] = np.cumsum(matrix, axis=0)
    prefix_square[1:] = np.cumsum(matrix**2, axis=0)

    cost = np.full((n, n + 1), np.inf, dtype=np.float64)
    for start in range(n):
        lengths = np.arange(1, n - start + 1, dtype=np.float64)
        totals = prefix[start + 1 :] - prefix[start]
        squares = prefix_square[start + 1 :] - prefix_square[start]
        segment = np.sum(squares - (totals**2) / lengths[:, None], axis=1) / float(d)
        cost[start, start + 1 :] = np.maximum(segment, 0.0)
    return cost


def segment_board_dp(
    board: pl.DataFrame,
    *,
    penalty: float,
    features: Sequence[str] = QUANTILE_FEATURE_COLUMNS,
) -> Segmentation:
    """Segment one fair-rank-ordered board by exact dynamic programming.

    Returns the same :class:`~ffdraft.tiers.segmentation.Segmentation` the PELT candidate
    does, so every downstream diagnostic, the stability bootstrap and the frozen selection
    rule work on either without knowing which produced it.
    """
    if board.height == 0:
        return Segmentation(
            penalty=penalty,
            ordinals=(),
            boundaries=(),
            diagnostics=(),
            within_tier_effect_sizes=(),
            version=DP_SEGMENTATION_VERSION,
        )
    matrix = standardize(board.select(list(features)).to_numpy().astype(np.float64))
    n = matrix.shape[0]
    cost = _segment_costs(matrix)

    # best[j] is the optimal total cost of segmenting the first j rows; previous[j] is where
    # the last segment of that solution starts.
    best = np.full(n + 1, np.inf, dtype=np.float64)
    previous = np.zeros(n + 1, dtype=np.int64)
    best[0] = 0.0
    for end in range(1, n + 1):
        candidates = best[:end] + cost[:end, end] + float(penalty)
        start = int(np.argmin(candidates))
        best[end] = candidates[start]
        previous[end] = start

    cuts: list[int] = []
    position = n
    while position > 0:
        cuts.append(position)
        position = int(previous[position])
    breaks = sorted(cuts)

    ordinals: list[int] = []
    start = 0
    for ordinal, end in enumerate(breaks):
        ordinals.extend([ordinal] * (end - start))
        start = end

    boundaries = tuple(int(value) for value in breaks[:-1])
    fair_ranks = (
        board.get_column("fair_rank").cast(pl.Int64).to_list()
        if "fair_rank" in board.columns
        else list(range(1, n + 1))
    )
    p50 = board.get_column("p50_vorp").cast(pl.Float64).to_numpy()
    spread = board.get_column("uncertainty").cast(pl.Float64).to_numpy()
    effects = adjacent_effect_sizes(p50, spread)

    diagnostics = tuple(
        BoundaryDiagnostic(
            fair_rank_above=int(fair_ranks[index - 1]),
            fair_rank_below=int(fair_ranks[index]),
            p50_cliff=float(p50[index - 1] - p50[index]),
            effect_size=float(effects[index - 1]),
            probability_lower_exceeds_upper=_probability_lower_exceeds_upper(
                float(effects[index - 1]),
            ),
        )
        for index in boundaries
    )
    boundary_positions = {index - 1 for index in boundaries}
    within = tuple(
        float(effects[index]) for index in range(effects.size) if index not in boundary_positions
    )
    return Segmentation(
        penalty=float(penalty),
        ordinals=tuple(ordinals),
        boundaries=boundaries,
        diagnostics=diagnostics,
        within_tier_effect_sizes=within,
        version=DP_SEGMENTATION_VERSION,
    )
