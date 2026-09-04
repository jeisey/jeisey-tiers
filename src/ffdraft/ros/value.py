"""Rest-of-season value above replacement, and the replacement question itself.

`docs/RELEASE2_ROADMAP.md` 11.5 is explicit that this is a decision rather than a detail:

> The replacement calculation must reflect the same league roster structure, but Phase 11
> must decide whether the correct baseline is the best unstarted player in a fresh league
> allocation, or a different explicitly documented ROS replacement interpretation. Do not
> silently assume preseason draft opportunity cost and in-season roster replacement are
> identical concepts.

Both interpretations are implemented here and both are measured; the choice is made on the
measured difference and recorded in ADR-071.

``fresh_allocation``
    Release 1's rule, unchanged: allocate the whole board into the league's starting slots
    and take the best player nobody starts. This is *draft* opportunity cost - what it costs
    to spend a pick rather than take the next player at the position.

``rostered_depth``
    The in-season rule: after the starting slots are filled, fill ``teams x bench`` bench
    places, then take the best player nobody *rosters*. This is *waiver* opportunity cost -
    what it costs to hold a player rather than take the best thing actually available.

    The bench is filled by **surplus over the starting-slot baseline**, not by raw points.
    Filling it by points would hoard quarterbacks, whose raw totals dwarf every other
    position and whose marginal value over a freely available quarterback is almost nothing;
    surplus is what a manager actually compares when deciding whom to hold, and it makes the
    rule self-consistent - the same quantity decides who is rostered and what replacement is.

Everything else is Release 1's machinery. The draw loop, the sampler, the per-player seeding
and the fair-ranking tie-break are :mod:`ffdraft.simulation`'s, called with a different
allocation rule; there is one draw loop in this repository, not two that could drift apart.

Public naming follows 11.5: the artifact-facing columns are ``ros_fair_rank``,
``ros_expected_vorp``, ``ros_vorp_p25/p50/p75`` and ``ros_tier``, so a rest-of-season number
can never be mistaken for a preseason one. The internal frames keep Release 1's column names
so the stability and convergence machinery reads them unchanged; :func:`to_public_names`
is the single place the two vocabularies meet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl

from ffdraft.config import LeaguePreset
from ffdraft.modeling.rules import Decision
from ffdraft.simulation.allocation import AllocationResult, PlayerPoints, allocate_starters

__all__ = [
    "REPLACEMENT_SELECTION",
    "ROS_PUBLIC_COLUMNS",
    "ROS_VALUE_VERSION",
    "RosReplacementRule",
    "RosReplacementSelection",
    "allocate_with_bench",
    "decide_replacement",
    "to_public_names",
]

#: Bump when the meaning of a rest-of-season value changes.
ROS_VALUE_VERSION = "ros_value_v1"


class RosReplacementRule(StrEnum):
    """The two replacement interpretations Phase 11 compares."""

    FRESH_ALLOCATION = "fresh_allocation"
    ROSTERED_DEPTH = "rostered_depth"

    @property
    def description(self) -> str:
        if self is RosReplacementRule.FRESH_ALLOCATION:
            return (
                "the best player nobody starts, after allocating the whole board into the "
                "league's starting slots (Release 1's preseason rule, unchanged)"
            )
        return (
            "the best player nobody rosters, after the starting slots and teams x bench "
            "bench places are filled, the bench by surplus over the starting-slot baseline"
        )


def allocate_with_bench(
    players: Sequence[PlayerPoints],
    preset: LeaguePreset,
) -> AllocationResult:
    """The in-season allocation: starters, then benches, then what is left over.

    Returns the same :class:`~ffdraft.simulation.allocation.AllocationResult` shape as
    :func:`~ffdraft.simulation.allocation.allocate_starters`, with the starters and unfilled
    slots untouched and only the replacement baseline redefined. Nothing downstream needs to
    know which rule produced it.
    """
    base = allocate_starters(players, preset)
    bench_places = preset.teams * preset.bench
    started = base.started_player_ids

    remaining = [player for player in players if player.player_id not in started]
    surplus: list[tuple[float, str, PlayerPoints]] = []
    for player in remaining:
        baseline = base.replacement_points.get(player.position)
        # A position whose pool was entirely consumed by starting slots has no baseline in
        # this draw. Such a player is treated as pure surplus: he is unambiguously worth
        # holding, because there is nothing behind him at all.
        margin = player.points if baseline is None else player.points - baseline
        surplus.append((margin, player.player_id, player))
    surplus.sort(key=lambda item: (-item[0], item[1]))
    benched = {item[1] for item in surplus[:bench_places]}

    replacement_points: dict[str, float | None] = {}
    replacement_player: dict[str, str | None] = {}
    positions = {player.position for player in players}
    for position in positions:
        pool = sorted(
            (
                player
                for player in remaining
                if player.position == position and player.player_id not in benched
            ),
            key=lambda player: (-player.points, player.player_id),
        )
        replacement_points[position] = pool[0].points if pool else None
        replacement_player[position] = pool[0].player_id if pool else None

    return AllocationResult(
        preset_id=base.preset_id,
        positional_starters=base.positional_starters,
        flex_starters=base.flex_starters,
        replacement_points=replacement_points,
        replacement_player_id=replacement_player,
        unfilled_slots=base.unfilled_slots,
    )


@dataclass(frozen=True)
class RosReplacementSelection:
    """Which replacement interpretation the rest-of-season board uses, and why.

    Frozen before the sensitivity was measured. The default is the **in-season** rule on
    semantic grounds: what it costs to hold a player in November is what the waiver wire
    offers instead, not what the twelfth-best starter scores. Release 1's rule is kept only
    if the two are indistinguishable on the board a reader actually sees, in which case
    continuity wins - the same "simplicity breaks a tie" convention the rest of the
    repository's decision rules use.
    """

    version: str = "ros_replacement_v1"
    default_rule: str = RosReplacementRule.ROSTERED_DEPTH.value
    fallback_rule: str = RosReplacementRule.FRESH_ALLOCATION.value
    min_indistinguishable_spearman: float = 0.999
    max_indistinguishable_rank_change: float = 1.0
    min_indistinguishable_top_50_overlap: float = 0.98

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_version": self.version,
            "default_rule": self.default_rule,
            "fallback_rule": self.fallback_rule,
            "min_indistinguishable_spearman": self.min_indistinguishable_spearman,
            "max_indistinguishable_rank_change": self.max_indistinguishable_rank_change,
            "min_indistinguishable_top_50_overlap": self.min_indistinguishable_top_50_overlap,
            "rules": [
                "the in-season rostered-depth interpretation is selected by default: an "
                "in-season decision's alternative is the best freely available player",
                "Release 1's fresh-allocation rule is retained only if every measured "
                "scenario is indistinguishable on fair-rank correlation, mean rank change "
                "inside the top 150 and top-50 overlap",
            ],
        }

    def indistinguishable(self, rows: Sequence[Mapping[str, Any]]) -> bool:
        if not rows:
            return False
        return all(
            float(row["fair_rank_spearman"]) >= self.min_indistinguishable_spearman
            and float(row["mean_abs_rank_change_top_150"]) <= self.max_indistinguishable_rank_change
            and float(row["top_50_overlap"]) >= self.min_indistinguishable_top_50_overlap
            for row in rows
        )


REPLACEMENT_SELECTION = RosReplacementSelection()


def decide_replacement(
    rows: Sequence[Mapping[str, Any]],
    *,
    criteria: RosReplacementSelection = REPLACEMENT_SELECTION,
) -> Decision:
    """Apply the frozen rule to the measured sensitivity. Pure: no data, no simulation."""
    if not rows:
        return Decision(
            rule=criteria.version,
            selected=criteria.default_rule,
            decisive=False,
            reasons=(),
            failures=("no scenario was measured",),
            evidence={"criteria": criteria.to_dict()},
        )
    tied = criteria.indistinguishable(rows)
    worst = min(float(row["fair_rank_spearman"]) for row in rows)
    largest = max(float(row["mean_abs_rank_change_top_150"]) for row in rows)
    overlap = min(float(row["top_50_overlap"]) for row in rows)
    summary = (
        f"across {len(rows)} scenario(s): worst fair-rank Spearman {worst:.4f}, largest mean "
        f"|rank change| in the top 150 {largest:.2f}, smallest top-50 overlap {overlap:.3f}"
    )
    if tied:
        return Decision(
            rule=criteria.version,
            selected=criteria.fallback_rule,
            decisive=True,
            reasons=(
                "the two interpretations are indistinguishable on the published board, so "
                "Release 1's rule is retained for continuity",
                summary,
            ),
            evidence={"criteria": criteria.to_dict()},
        )
    return Decision(
        rule=criteria.version,
        selected=criteria.default_rule,
        decisive=True,
        reasons=(
            "the two interpretations disagree materially, so the in-season meaning is used",
            summary,
        ),
        evidence={"criteria": criteria.to_dict()},
    )


#: Release 1's internal column -> the Phase-11 public name.
ROS_PUBLIC_COLUMNS: Mapping[str, str] = {
    "fair_rank": "ros_fair_rank",
    "position_rank": "ros_position_rank",
    "expected_vorp": "ros_expected_vorp",
    "p25_vorp": "ros_vorp_p25",
    "p50_vorp": "ros_vorp_p50",
    "p75_vorp": "ros_vorp_p75",
    "p10_vorp": "ros_vorp_p10",
    "p90_vorp": "ros_vorp_p90",
    "expected_points": "ros_expected_points",
    "p50_points": "ros_points_p50",
    "tier_ordinal": "ros_tier",
    "tier_label": "ros_tier_label",
    "uncertainty": "ros_uncertainty",
}


def to_public_names(frame: pl.DataFrame) -> pl.DataFrame:
    """Rename an internal board to the Phase-11 public vocabulary.

    A rest-of-season fair rank must never share a column name with a preseason one: they are
    different quantities computed from different models over different horizons, and a
    reader who sees ``fair_rank`` is entitled to assume it is the draft one.
    """
    mapping = {
        internal: public
        for internal, public in ROS_PUBLIC_COLUMNS.items()
        if internal in frame.columns
    }
    return frame.rename(mapping)
