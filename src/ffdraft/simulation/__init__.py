"""League roster allocation and replacement baselines.

Phase 2 uses this package for realized-VORP labels. Phase 4 adds the Monte Carlo sampler
around the same allocation, rather than reimplementing it.
"""

from __future__ import annotations

from ffdraft.simulation.allocation import (
    AllocationResult,
    PlayerPoints,
    allocate_starters,
    replacement_baselines,
    vorp_for_players,
)

__all__ = [
    "AllocationResult",
    "PlayerPoints",
    "allocate_starters",
    "replacement_baselines",
    "vorp_for_players",
]
