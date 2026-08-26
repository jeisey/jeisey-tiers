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

__all__ = ["MarketIdentity", "load_market_identity", "mapping_from", "supplement_roster"]


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
    players: pl.DataFrame | None = None,
) -> MarketIdentity:
    """Build the canonical registry for ``season``.

    Frames may be supplied, which is how every network-free test drives this path. When
    they are not, the nflverse loaders are called for the *target* season.

    The spine is that season's roster **plus** nflverse's own player master, filtered to
    players whose last season reaches ``season`` (ADR-055). The roster alone used to be the
    whole answer, on the reasoning that a current capture is asking "who is on a roster
    now". It turned out not to answer that: on 2026-08-26 `load_rosters(2026)` was missing
    101 skill-position players who were on NFL rosters, Stefon Diggs and Keenan Allen among
    them, and a player the registry does not contain cannot be reached by *either* market
    bridge, however well the crosswalk knows him.

    The supplement adds rows, never overrides them: a gsis id already on the roster keeps
    the roster's record, which is the richer one (depth chart, Sleeper id, more crosswalks).
    """
    stamped = as_of or utc_now()
    checks: list[QualityCheck] = []

    if roster is None or player_ids is None or players is None:
        import nflreadpy

        from ffdraft.sources.nflverse import (
            NflversePlayerIdsAdapter,
            NflversePlayersAdapter,
            NflverseRosterAdapter,
        )

        if roster is None:
            roster_adapter = NflverseRosterAdapter()
            roster_batch = roster_adapter.normalize(
                nflreadpy.load_rosters(seasons=[season]),
                season=season,
                retrieved_at=stamped,
            )
            checks.extend(roster_adapter.validate_raw(roster_batch).checks)
            roster = roster_batch.frame
        if players is None:
            players_adapter = NflversePlayersAdapter()
            players_batch = players_adapter.normalize(
                nflreadpy.load_players(),
                season=season,
                retrieved_at=stamped,
            )
            checks.extend(players_adapter.validate_raw(players_batch).checks)
            players = players_batch.frame
        if player_ids is None:
            ids_adapter = NflversePlayerIdsAdapter()
            ids_batch = ids_adapter.normalize(
                nflreadpy.load_ff_playerids(),
                retrieved_at=stamped,
            )
            checks.extend(ids_adapter.validate_raw(ids_batch).checks)
            player_ids = ids_batch.frame

    spine, supplement_check = supplement_roster(roster, players, season=season)
    if supplement_check is not None:
        checks.append(supplement_check)
    registry = build_registry(spine, player_ids=player_ids)
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


def supplement_roster(
    roster: pl.DataFrame,
    players: pl.DataFrame | None,
    *,
    season: int,
) -> tuple[pl.DataFrame, QualityCheck | None]:
    """The season's roster, plus the players it left out.

    Both frames are ``ROSTER_CONTRACT`` shaped, so this is a filtered concat rather than a
    join. The roster wins every collision: it is the richer record, and the supplement
    exists to add players, not to restate them.

    The count is reported rather than assumed. A supplement that suddenly adds hundreds of
    players, or none at all, means the upstream files disagree about who is in the league,
    and that is worth seeing in a build log before it is worth debugging in a board.
    """
    if players is None or players.is_empty():
        return roster, None
    known = roster.get_column("gsis_id").drop_nulls().to_list()
    extra = players.filter(~pl.col("gsis_id").is_in(known)).select(roster.columns)
    if extra.is_empty():
        return roster, None
    return (
        pl.concat([roster, extra], how="vertical"),
        QualityCheck.ok(
            "identity.roster_supplemented",
            stage="identity.market",
            message=(
                "players active this season that the season roster file omits were added to "
                "the canonical spine; without them their market prices cannot join (ADR-055)"
            ),
            observed=f"{extra.height} player(s) added to {roster.height} roster row(s)",
        ),
    )
