"""The two tier segmentation algorithms, named so a build can record which one it used.

`docs/MODELING.md` section 14 names change-point segmentation as the primary candidate and
exact quantile-dispersion dynamic programming as the documented alternative, to be reached
only when the primary proves unstable under measured tests. Both are implemented, so a
production board is a function of *which* one was promoted as much as of the penalty.

That makes the algorithm a frozen parameter rather than an assumption, and this module is
the neutral place both the study and the production build can name it from without either
importing the other.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from ffdraft.tiers.dynamic import DP_SEGMENTATION_VERSION, segment_board_dp
from ffdraft.tiers.segmentation import SEGMENTATION_VERSION, Segmentation, segment_board

__all__ = [
    "ALGORITHM_VERSIONS",
    "ALTERNATIVE_ALGORITHM",
    "PRIMARY_ALGORITHM",
    "segment_with",
]

#: The primary candidate and the documented alternative, in the order ADR-030 requires them
#: to be tried: the alternative is only reached because the primary failed a frozen rule.
PRIMARY_ALGORITHM = "pelt_rbf"
ALTERNATIVE_ALGORITHM = "dp_quantile"

#: Each algorithm's own version string, which is what an artifact records.
ALGORITHM_VERSIONS: Mapping[str, str] = {
    PRIMARY_ALGORITHM: SEGMENTATION_VERSION,
    ALTERNATIVE_ALGORITHM: DP_SEGMENTATION_VERSION,
}


def segment_with(algorithm: str, board: pl.DataFrame, *, penalty: float) -> Segmentation:
    """Segment one ranked board with the named algorithm.

    An unknown name raises rather than falling back to the primary: a build that cannot say
    which algorithm drew its tiers should not draw them.
    """
    if algorithm == PRIMARY_ALGORITHM:
        return segment_board(board, penalty=penalty)
    if algorithm == ALTERNATIVE_ALGORITHM:
        return segment_board_dp(board, penalty=penalty)
    raise ValueError(f"unknown segmentation algorithm {algorithm!r}")
