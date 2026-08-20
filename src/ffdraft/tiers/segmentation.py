"""Contiguous natural tier segmentation.

`docs/MODELING.md` section 14: tiers are contiguous in fair-rank order, their number is
discovered rather than chosen, and the only input is the intrinsic simulated VORP
distribution. No position quota, no "top five are S", no hand-moved players.

The promoted candidate is change-point segmentation - ``ruptures.Pelt(model="rbf")`` over a
rank-ordered feature matrix of standardized ``P25``, ``P50``, ``P75`` and spread. Four
numbers rather than one, because a tier break is not only a drop in the middle of the
distribution: two players with the same median but very different floors belong to different
decision sets, and an RBF cost over the whole summary sees that where a cost over the median
alone would not.

Segment boundaries are where the algorithm says the distribution changes, so the number of
tiers is whatever the penalty and the data produce together. ``min_size=1`` deliberately
permits a singleton tier: a genuinely isolated top player is a real thing a draft board
should be able to say. Proliferation is controlled by the penalty and measured by the
singleton rate, not forbidden by construction.

Every boundary carries diagnostics computed the same way for boundary and non-boundary
adjacent pairs, which is what makes "boundaries separate more than a typical pair inside a
tier" a measurable claim rather than an impression.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
import ruptures as rpt
from numpy.typing import NDArray

from ffdraft.tiers.labels import tier_label

__all__ = [
    "SEGMENTATION_VERSION",
    "TIER_FEATURE_COLUMNS",
    "BoundaryDiagnostic",
    "Segmentation",
    "adjacent_effect_sizes",
    "segment_board",
    "standardize",
]

Floats = NDArray[np.float64]

#: Bump when the segmentation construction changes in a way that moves boundaries.
SEGMENTATION_VERSION = "pelt_rbf_vorp_summary_v1"

#: The rank-ordered feature matrix, exactly `docs/MODELING.md` section 14.2's suggestion.
TIER_FEATURE_COLUMNS: tuple[str, ...] = ("p25_vorp", "p50_vorp", "p75_vorp", "uncertainty")

#: An IQR-to-standard-deviation conversion for a normal distribution. Used only to put an
#: adjacent-pair gap on a comparable scale, never to claim the outcome is normal.
_IQR_TO_SD = 1.349


def standardize(matrix: Floats) -> Floats:
    """Z-score each column against the board being segmented.

    The board is the population here, not a sample from one: the question is where *this*
    ordering breaks. A column with no variation is left at zero rather than divided by it.
    """
    values = np.asarray(matrix, dtype=np.float64)
    if values.size == 0:
        return values
    centre = values.mean(axis=0)
    scale = values.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    return (values - centre) / scale


@dataclass(frozen=True, slots=True)
class BoundaryDiagnostic:
    """What separates the two players either side of one tier boundary."""

    fair_rank_above: int
    fair_rank_below: int
    p50_cliff: float
    effect_size: float
    probability_lower_exceeds_upper: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fair_rank_above": self.fair_rank_above,
            "fair_rank_below": self.fair_rank_below,
            "p50_cliff": self.p50_cliff,
            "effect_size": self.effect_size,
            "probability_lower_exceeds_upper": self.probability_lower_exceeds_upper,
        }


@dataclass(frozen=True)
class Segmentation:
    """One board's tiers, with everything needed to judge them."""

    penalty: float
    ordinals: tuple[int, ...]
    boundaries: tuple[int, ...]
    diagnostics: tuple[BoundaryDiagnostic, ...]
    within_tier_effect_sizes: tuple[float, ...]
    version: str = SEGMENTATION_VERSION

    @property
    def tier_count(self) -> int:
        return len(set(self.ordinals))

    @property
    def sizes(self) -> tuple[int, ...]:
        counts: dict[int, int] = {}
        for ordinal in self.ordinals:
            counts[ordinal] = counts.get(ordinal, 0) + 1
        return tuple(counts[key] for key in sorted(counts))

    @property
    def singleton_rate(self) -> float:
        sizes = self.sizes
        return float(np.mean([size == 1 for size in sizes])) if sizes else float("nan")

    @property
    def largest_tier_share(self) -> float:
        sizes = self.sizes
        return float(max(sizes) / sum(sizes)) if sizes else float("nan")

    @property
    def mean_boundary_effect_size(self) -> float:
        values = [
            item.effect_size for item in self.diagnostics if item.effect_size == item.effect_size
        ]
        return float(np.mean(values)) if values else float("nan")

    @property
    def median_within_tier_effect_size(self) -> float:
        values = [value for value in self.within_tier_effect_sizes if value == value]
        return float(np.median(values)) if values else float("nan")

    def labels(self) -> tuple[str, ...]:
        return tuple(tier_label(ordinal) for ordinal in self.ordinals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segmentation_version": self.version,
            "penalty": self.penalty,
            "tier_count": self.tier_count,
            "sizes": list(self.sizes),
            "boundaries": list(self.boundaries),
            "singleton_rate": self.singleton_rate,
            "largest_tier_share": self.largest_tier_share,
            "mean_boundary_effect_size": self.mean_boundary_effect_size,
            "median_within_tier_effect_size": self.median_within_tier_effect_size,
            "boundary_diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _spread_to_sd(spread: Floats) -> Floats:
    """An IQR expressed as a standard deviation, floored so a zero spread cannot divide."""
    return np.maximum(np.abs(spread) / _IQR_TO_SD, 1e-9)


def adjacent_effect_sizes(p50: Floats, spread: Floats) -> Floats:
    """Standardized gap between every adjacent pair on the board.

    ``gap / sqrt(sd_above^2 + sd_below^2)``, with each player's standard deviation estimated
    from his own interquartile range. Computing it identically for boundary and non-boundary
    pairs is the whole point: it makes "this boundary separates more than a typical pair
    inside a tier" a ratio rather than an assertion.
    """
    above, below = p50[:-1], p50[1:]
    sd_above, sd_below = _spread_to_sd(spread[:-1]), _spread_to_sd(spread[1:])
    return (above - below) / np.sqrt(sd_above**2 + sd_below**2)


def _probability_lower_exceeds_upper(effect: float) -> float:
    """P(the lower-ranked player outscores the higher-ranked one) under a normal proxy.

    A deliberately transparent approximation: each player's simulated VORP is summarised by
    its median and interquartile range, and the gap is read off a normal curve. It answers
    "is this boundary a coin flip or a cliff?" without pretending to be the exact overlap of
    two Monte Carlo samples.
    """
    from ffdraft.modeling.gaussian import norm_cdf

    return float(norm_cdf(np.asarray(-effect, dtype=np.float64)))


def segment_board(
    board: pl.DataFrame,
    *,
    penalty: float,
    features: Sequence[str] = TIER_FEATURE_COLUMNS,
    min_size: int = 1,
) -> Segmentation:
    """Segment one fair-rank-ordered board into contiguous tiers.

    ``board`` must already be sorted by ``fair_rank`` and carry the feature columns. The
    result's ``ordinals`` are aligned to the board's row order, so tier membership is
    contiguous in fair rank by construction rather than by a later check.
    """
    if board.height == 0:
        return Segmentation(
            penalty=penalty, ordinals=(), boundaries=(), diagnostics=(), within_tier_effect_sizes=()
        )
    matrix = standardize(board.select(list(features)).to_numpy().astype(np.float64))
    if board.height <= 2:
        breaks: list[int] = [board.height]
    else:
        algorithm = rpt.Pelt(model="rbf", min_size=min_size, jump=1).fit(matrix)
        breaks = [int(value) for value in algorithm.predict(pen=float(penalty))]

    ordinals: list[int] = []
    start = 0
    for ordinal, end in enumerate(breaks):
        ordinals.extend([ordinal] * (end - start))
        start = end

    boundaries = tuple(int(value) for value in breaks[:-1])
    fair_ranks = (
        board.get_column("fair_rank").cast(pl.Int64).to_list()
        if "fair_rank" in board.columns
        else list(range(1, board.height + 1))
    )
    p50 = board.get_column("p50_vorp").cast(pl.Float64).to_numpy()
    spread = board.get_column("uncertainty").cast(pl.Float64).to_numpy()
    effects = adjacent_effect_sizes(p50, spread)

    diagnostics: list[BoundaryDiagnostic] = []
    for index in boundaries:
        gap = index - 1
        diagnostics.append(
            BoundaryDiagnostic(
                fair_rank_above=int(fair_ranks[gap]),
                fair_rank_below=int(fair_ranks[index]),
                p50_cliff=float(p50[gap] - p50[index]),
                effect_size=float(effects[gap]),
                probability_lower_exceeds_upper=_probability_lower_exceeds_upper(
                    float(effects[gap]),
                ),
            ),
        )
    boundary_positions = {index - 1 for index in boundaries}
    within = tuple(
        float(effects[index]) for index in range(effects.size) if index not in boundary_positions
    )
    return Segmentation(
        penalty=float(penalty),
        ordinals=tuple(ordinals),
        boundaries=boundaries,
        diagnostics=tuple(diagnostics),
        within_tier_effect_sizes=within,
    )
