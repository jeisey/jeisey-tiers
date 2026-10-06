"""Drive breadth above expectation: does his involvement recur across possessions? (ADR-103)

The role rails answer *how much* of the offense a player gets. This answers a different
question: given how many opportunities he had in a game and how the team's opportunities fell
across its drives, did his involvement spread across many possessions or cluster into a few?

For one completed appearance ``g``:

* ``n_d`` — eligible team slots in drive ``d`` (the position's definition, below);
  ``N = Σ n_d``; ``D`` — drives with at least one eligible slot;
* ``K`` — the player's eligible opportunities; ``A`` — drives holding at least one of them;
* ``E = Σ_d [1 − C(N − n_d, K) / C(N, K)]`` — the drives ``K`` opportunities would reach if
  they were placed uniformly at random among the game's ``N`` slots. An impossible
  combination is zero, so a drive that cannot be missed contributes exactly one.

``E`` is the rarefaction (occupancy) expectation: the probability a drive is missed by a
uniform draw of ``K`` of ``N`` slots without replacement is ``C(N − n_d, K) / C(N, K)``. It is a
neutral allocation reference, not this site's projection of anything.

Over the latest ``W`` completed appearances: ``breadth_gap_pp = 100 · Σ (A − E) / Σ D``. The
reference is computed per game before summing — pooling slots across games would erase a
week-to-week change of role.

Positive: his involvement reached more drives than the same count placed at random would;
negative: it clustered. **Neither sign is good or bad fantasy value**, and a low-volume player
is not better than a star because his gap is larger. This module scores no yards, touchdowns,
efficiency, market or model value, and no model reads it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import comb

__all__ = [
    "BREADTH_METHOD_VERSION",
    "BREADTH_WINDOW_APPEARANCES",
    "DISPLAY_MIN_APPEARANCES",
    "DISPLAY_MIN_ELIGIBLE_DRIVES",
    "DISPLAY_MIN_OPPORTUNITIES",
    "BreadthWindow",
    "GameBreadth",
    "expected_reach",
    "game_breadth",
    "window_breadth",
]

#: Bump when a definition, an exclusion or the window changes meaning (ADR-103).
BREADTH_METHOD_VERSION = "drive_breadth_v1"

#: The latest completed appearances the published reading spans.
BREADTH_WINDOW_APPEARANCES = 4

#: Provisional display minimums (ADR-103): a display rule, not an established reliability bar.
DISPLAY_MIN_APPEARANCES = 3
DISPLAY_MIN_ELIGIBLE_DRIVES = 20
DISPLAY_MIN_OPPORTUNITIES = 6


def expected_reach(slots_per_drive: Sequence[int], opportunities: int) -> float:
    """``E``: drives reached by ``opportunities`` placed uniformly among the game's slots.

    Exact integer binomials (``math.comb``), so a 70-slot game has no floating-point
    cancellation; ``comb(n, k)`` is zero when ``k > n``, which is the "impossible combination
    contributes zero" rule — that drive cannot be missed and counts one.
    """
    if opportunities < 0:
        raise ValueError("opportunities must be non-negative")
    if any(slots < 0 for slots in slots_per_drive):
        raise ValueError("a drive cannot hold a negative number of slots")
    total = sum(slots_per_drive)
    if opportunities > total:
        raise ValueError(f"{opportunities} opportunities cannot fit {total} eligible slots")
    if opportunities == 0:
        return 0.0
    denominator = comb(total, opportunities)
    missed = sum(comb(total - slots, opportunities) for slots in slots_per_drive if slots > 0)
    drives = sum(1 for slots in slots_per_drive if slots > 0)
    return drives - missed / denominator


@dataclass(frozen=True, slots=True)
class GameBreadth:
    """One completed appearance's arithmetic."""

    season: int
    week: int
    eligible_drives: int
    eligible_slots: int
    opportunities: int
    reached_drives: int
    expected_drives: float

    @property
    def gap(self) -> float:
        return self.reached_drives - self.expected_drives


def game_breadth(
    *,
    season: int,
    week: int,
    slots_by_drive: Mapping[int, int],
    opportunities_by_drive: Mapping[int, int],
) -> GameBreadth:
    """One appearance from its per-drive counts. A drive with no eligible slot is not a drive.

    ``opportunities_by_drive`` may only name drives that hold eligible slots, and never more
    opportunities than slots: a player opportunity *is* one of the team's eligible slots.
    """
    slots = {drive: count for drive, count in slots_by_drive.items() if count > 0}
    for drive, count in opportunities_by_drive.items():
        if count < 0:
            raise ValueError("negative opportunities")
        if count and count > slots.get(drive, 0):
            raise ValueError(f"drive {drive!r}: {count} opportunities exceed its eligible slots")
    k = sum(opportunities_by_drive.values())
    reached = sum(1 for count in opportunities_by_drive.values() if count > 0)
    return GameBreadth(
        season=season,
        week=week,
        eligible_drives=len(slots),
        eligible_slots=sum(slots.values()),
        opportunities=k,
        reached_drives=reached,
        expected_drives=expected_reach(list(slots.values()), k),
    )


@dataclass(frozen=True, slots=True)
class BreadthWindow:
    """The published reading over the latest completed appearances."""

    appearances: int
    first_week: int | None
    last_week: int | None
    eligible_drives: int
    reached_drives: int
    expected_drives: float
    opportunities: int
    breadth_gap_pp: float | None
    displayable: bool
    #: Why it is not displayed, when it is not: the first minimum it misses.
    withheld_reason: str | None


def window_breadth(
    games: Iterable[GameBreadth],
    *,
    window: int = BREADTH_WINDOW_APPEARANCES,
    min_appearances: int = DISPLAY_MIN_APPEARANCES,
    min_drives: int = DISPLAY_MIN_ELIGIBLE_DRIVES,
    min_opportunities: int = DISPLAY_MIN_OPPORTUNITIES,
) -> BreadthWindow:
    """``100 · Σ(A − E) / Σ D`` over the latest ``window`` appearances, with the display rule.

    ``games`` are completed appearances only — a bye or a missed game is not a zero-role game
    and never enters. The gap is computed whenever there is a denominator; ``displayable``
    says whether it clears the provisional minimums, so the page can show "too few" rather
    than a number that looks like "average".
    """
    ordered = sorted(games, key=lambda game: (game.season, game.week))[-window:] if window else []
    drives = sum(game.eligible_drives for game in ordered)
    reached = sum(game.reached_drives for game in ordered)
    expected = sum(game.expected_drives for game in ordered)
    opportunities = sum(game.opportunities for game in ordered)
    gap = None if drives == 0 else round(100.0 * (reached - expected) / drives, 1)
    reason: str | None = None
    if len(ordered) < min_appearances:
        reason = "too_few_appearances"
    elif drives < min_drives:
        reason = "too_few_eligible_drives"
    elif opportunities < min_opportunities:
        reason = "too_few_opportunities"
    return BreadthWindow(
        appearances=len(ordered),
        first_week=ordered[0].week if ordered else None,
        last_week=ordered[-1].week if ordered else None,
        eligible_drives=drives,
        reached_drives=reached,
        expected_drives=round(expected, 3),
        opportunities=opportunities,
        breadth_gap_pp=gap,
        displayable=reason is None and gap is not None,
        withheld_reason=reason,
    )
