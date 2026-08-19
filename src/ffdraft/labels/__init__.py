"""Historical outcome labels: fantasy points and realized VORP."""

from __future__ import annotations

from ffdraft.labels.fantasy import build_fantasy_labels, season_point_totals
from ffdraft.labels.vorp import (
    REPLACEMENT_UNAVAILABLE_FLAG,
    build_vorp_labels,
    vorp_for_one_group,
)

__all__ = [
    "REPLACEMENT_UNAVAILABLE_FLAG",
    "build_fantasy_labels",
    "build_vorp_labels",
    "season_point_totals",
    "vorp_for_one_group",
]
