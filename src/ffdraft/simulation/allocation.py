"""Starter/FLEX allocation and replacement baselines.

This is the algorithm `docs/MODELING.md` section 12 specifies, and it is deliberately
independent of *where* the points came from. Phase 2 feeds it a player's **actual** season
points to build realized-VORP labels; Phase 4 will feed it one Monte Carlo **draw** per
player to build simulated VORP distributions. Both need the same answer to the same
question - "who would a league of this shape actually start, and what does the best player
nobody started score?" - so there is one implementation rather than two that can disagree.

The procedure, per league preset:

1. rank each position's pool by points, descending;
2. fill every mandatory positional starting slot (``teams x starters[position]``);
3. fill FLEX slots globally from the best remaining flex-eligible players;
4. the replacement baseline for a position is the highest-scoring player at that position
   that steps 2 and 3 did **not** consume;
5. a player's VORP is their points minus their position's replacement baseline.

Nothing here knows about ADP, market cost or expert ranks, and nothing here may: scarcity
is derived from roster shape and points alone, which is what makes intrinsic DraftValue
market-independent (ADR-002).

Ties are broken by ``player_id`` ascending, so an allocation is a pure function of its
inputs. Two players on identical points produce the same starters on every run and every
machine.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ffdraft.config import FLEX_SLOT, LeaguePreset

__all__ = [
    "AllocationResult",
    "PlayerPoints",
    "allocate_starters",
    "replacement_baselines",
    "vorp_for_players",
]


@dataclass(frozen=True, slots=True)
class PlayerPoints:
    """One player's points for one allocation. ``points`` may be actual or sampled."""

    player_id: str
    position: str
    points: float


@dataclass(frozen=True, slots=True)
class AllocationResult:
    """Who starts, what replacement costs, and where the league ran out of players."""

    preset_id: str
    positional_starters: Mapping[str, tuple[str, ...]]
    flex_starters: tuple[str, ...]
    replacement_points: Mapping[str, float | None]
    replacement_player_id: Mapping[str, str | None]
    unfilled_slots: Mapping[str, int]

    @property
    def started_player_ids(self) -> frozenset[str]:
        starters = {player for group in self.positional_starters.values() for player in group}
        return frozenset(starters | set(self.flex_starters))

    @property
    def fully_staffed(self) -> bool:
        """Whether every declared starting slot found a player."""
        return not any(self.unfilled_slots.values())

    def replacement_for(self, position: str) -> float | None:
        return self.replacement_points.get(position)


def _sorted_pool(players: Iterable[PlayerPoints]) -> list[PlayerPoints]:
    """Descending by points, then ascending by ``player_id``: a total, stable order."""
    return sorted(players, key=lambda player: (-player.points, player.player_id))


def allocate_starters(
    players: Sequence[PlayerPoints],
    preset: LeaguePreset,
) -> AllocationResult:
    """Run the roster allocation for one league preset."""
    pools: dict[str, list[PlayerPoints]] = {}
    for player in players:
        pools.setdefault(player.position, []).append(player)
    for position in pools:
        pools[position] = _sorted_pool(pools[position])

    cursors: dict[str, int] = dict.fromkeys(pools, 0)
    positional: dict[str, tuple[str, ...]] = {}
    unfilled: dict[str, int] = {}

    # Dedicated slots first, in a fixed alphabetical order. The order cannot change the
    # outcome - dedicated slots never compete for the same player - but fixing it keeps the
    # result identical across Python versions and dict orderings.
    for position in sorted(slot for slot in preset.starters if slot != FLEX_SLOT):
        wanted = preset.teams * preset.starters[position]
        pool = pools.get(position, [])
        taken = pool[:wanted]
        cursors[position] = len(taken)
        positional[position] = tuple(player.player_id for player in taken)
        if wanted > len(taken):
            unfilled[position] = wanted - len(taken)

    # FLEX is a global competition among the remaining flex-eligible players.
    flex_wanted = preset.teams * preset.starters.get(FLEX_SLOT, 0)
    remaining_flex = _sorted_pool(
        player
        for position in preset.flex_eligible
        for player in pools.get(position, [])[cursors.get(position, 0) :]
    )
    flex_taken = remaining_flex[:flex_wanted]
    for player in flex_taken:
        cursors[player.position] = cursors.get(player.position, 0) + 1
    if flex_wanted > len(flex_taken):
        unfilled[FLEX_SLOT] = flex_wanted - len(flex_taken)

    replacement_points: dict[str, float | None] = {}
    replacement_player: dict[str, str | None] = {}
    for position, pool in pools.items():
        # `cursors[position]` counts everyone this position lost to a dedicated slot or to
        # FLEX. Because both took from the front of the same sorted pool, the next entry is
        # exactly "the best player nobody started".
        index = cursors.get(position, 0)
        if index < len(pool):
            replacement_points[position] = pool[index].points
            replacement_player[position] = pool[index].player_id
        else:
            replacement_points[position] = None
            replacement_player[position] = None

    return AllocationResult(
        preset_id=preset.preset_id,
        positional_starters=positional,
        flex_starters=tuple(player.player_id for player in flex_taken),
        replacement_points=replacement_points,
        replacement_player_id=replacement_player,
        unfilled_slots=unfilled,
    )


def replacement_baselines(
    players: Sequence[PlayerPoints],
    preset: LeaguePreset,
) -> Mapping[str, float | None]:
    """Convenience wrapper returning only the replacement baselines."""
    return allocate_starters(players, preset).replacement_points


def vorp_for_players(
    players: Sequence[PlayerPoints],
    preset: LeaguePreset,
) -> tuple[AllocationResult, dict[str, float | None]]:
    """Allocate, then return VORP per player.

    A player whose position has no replacement baseline - the pool was entirely consumed by
    starting slots - gets ``None`` rather than an invented zero. Pretending replacement is
    zero when the league literally cannot field a bench would understate scarcity for every
    player at that position, which is the opposite of the truth.
    """
    allocation = allocate_starters(players, preset)
    vorp: dict[str, float | None] = {}
    for player in players:
        baseline = allocation.replacement_points.get(player.position)
        vorp[player.player_id] = None if baseline is None else player.points - baseline
    return allocation, vorp
