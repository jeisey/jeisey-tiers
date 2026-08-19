"""Contiguous natural tier segmentation.

The package consumes ranked intrinsic distribution summaries and nothing else. It has no
knowledge of ADP, expert rank or any market quantity, and `docs/ARCHITECTURE.md` keeps it
that way: whatever the arbitrage phase does with a tier, a tier never learns about it.
"""

from __future__ import annotations

from ffdraft.tiers.labels import LETTER_LABELS, tier_label
from ffdraft.tiers.segmentation import (
    SEGMENTATION_VERSION,
    TIER_FEATURE_COLUMNS,
    BoundaryDiagnostic,
    Segmentation,
    adjacent_effect_sizes,
    segment_board,
    standardize,
)
from ffdraft.tiers.stability import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    StabilityReport,
    adjusted_rand_index,
    bootstrap_stability,
    summarise_from_draws,
)

__all__ = [
    "DEFAULT_BOOTSTRAP_REPLICATES",
    "LETTER_LABELS",
    "SEGMENTATION_VERSION",
    "TIER_FEATURE_COLUMNS",
    "BoundaryDiagnostic",
    "Segmentation",
    "StabilityReport",
    "adjacent_effect_sizes",
    "adjusted_rand_index",
    "bootstrap_stability",
    "segment_board",
    "standardize",
    "summarise_from_draws",
    "tier_label",
]
