"""Canonical identity for market and status captures.

**Boundary module.** Market data only.

The identity layer itself is Phase-1 production code (`ffdraft.identity`), unchanged and
fail-closed. This module only assembles its inputs for a *current* capture: the target
season's nflverse roster (the primary ``espn_id`` bridge and the ``sleeper_id`` join key)
and the dynastyprocess crosswalk mirror (the secondary ``mfl_id`` bridge).

Nothing here relaxes anything. A name never resolves a record, a disagreement between the
two bridges fails closed, and a poisoned crosswalk index refuses every lookup through it
(ADR-019).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.identity.registry import CanonicalRegistry, build_registry
from ffdraft.timeutil import utc_now

__all__ = ["MarketIdentity", "load_market_identity", "mapping_from"]


def mapping_from(frame: pl.DataFrame, key: str, value: str) -> dict[str, str]:
    """A ``{key: value}`` lookup from two frame columns, skipping null on either side."""
    if frame.is_empty() or key not in frame.columns or value not in frame.columns:
        return {}
    return {
        str(row[key]): str(row[value])
        for row in frame.select(key, value).iter_rows(named=True)
        if row[key] is not None and row[value] is not None
    }


@dataclass(frozen=True)
class MarketIdentity:
    """The canonical registry plus the crosswalk inputs a market resolution needs."""

    registry: CanonicalRegistry
    #: ``mfl_id -> gsis_id`` from the dynastyprocess mirror: the *secondary* bridge.
    gsis_by_mfl_id: Mapping[str, str]
    roster: pl.DataFrame
    player_ids: pl.DataFrame
    checks: tuple[QualityCheck, ...] = field(default=())
    retrieved_at_utc: datetime | None = None


def load_market_identity(
    season: int,
    *,
    as_of: datetime | None = None,
    roster: pl.DataFrame | None = None,
    player_ids: pl.DataFrame | None = None,
) -> MarketIdentity:
    """Build the canonical registry for ``season``.

    Frames may be supplied, which is how every network-free test drives this path. When
    they are not, the nflverse loaders are called for the *target* season — a current
    capture is asking "who is on a roster now", which is exactly what that season's roster
    answers, and unlike the historical builder it has no anchor to respect (ADR-011).
    """
    stamped = as_of or utc_now()
    checks: list[QualityCheck] = []

    if roster is None or player_ids is None:
        import nflreadpy

        from ffdraft.sources.nflverse import NflversePlayerIdsAdapter, NflverseRosterAdapter

        if roster is None:
            roster_adapter = NflverseRosterAdapter()
            roster_batch = roster_adapter.normalize(
                nflreadpy.load_rosters(seasons=[season]),
                season=season,
                retrieved_at=stamped,
            )
            checks.extend(roster_adapter.validate_raw(roster_batch).checks)
            roster = roster_batch.frame
        if player_ids is None:
            ids_adapter = NflversePlayerIdsAdapter()
            ids_batch = ids_adapter.normalize(
                nflreadpy.load_ff_playerids(),
                retrieved_at=stamped,
            )
            checks.extend(ids_adapter.validate_raw(ids_batch).checks)
            player_ids = ids_batch.frame

    registry = build_registry(roster, player_ids=player_ids)
    checks.extend(registry.checks)
    return MarketIdentity(
        registry=registry,
        gsis_by_mfl_id=mapping_from(player_ids, "mfl_id", "gsis_id"),
        roster=roster,
        player_ids=player_ids,
        checks=tuple(checks),
        retrieved_at_utc=stamped,
    )


def resolution_index(outcomes: Sequence[Any]) -> dict[str, str]:
    """``external_player_id -> player_id`` for resolved outcomes only."""
    return {
        outcome.external_player_id: outcome.player_id
        for outcome in outcomes
        if outcome.resolved and outcome.player_id
    }
