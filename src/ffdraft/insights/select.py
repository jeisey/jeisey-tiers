"""``insights_select_v1``: family order, one story per player, and the lead — never a score.

1. **Within a family** stories are grouped (by variant; weekly upside by position), each group
   ordered by the family's published ordering, capped at ``variant_cap``, numbered
   (``family_rank``), and the groups interleaved round-robin so one variant cannot crowd out
   another.
2. **One story per player**, across families in editorial order (:data:`FAMILIES`): the first
   story keeps him and lists the others in ``also_qualifies``.
3. **The lead** walks the families round-robin in the same order; each pass takes each
   family's next story that keeps the family cap and the per-team cap, until ``lead_max`` or a
   pass that adds nothing. Empty families are skipped, so the lead can be shorter than the cap:
   it is a ceiling, not a quota.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ffdraft.insights.families import Draft
from ffdraft.insights.rules import FAMILIES, VARIANTS, InsightRule, SelectionRule

__all__ = ["Selection", "select"]


@dataclass(slots=True)
class Selection:
    #: Kept stories in publication order (family order, then interleaved family order).
    stories: list[Draft] = field(default_factory=list)
    lead_rank: dict[str, int] = field(default_factory=dict)
    also: dict[str, list[str]] = field(default_factory=dict)
    #: ``(family, reason) -> stories dropped``.
    suppressed: Counter[tuple[str, str]] = field(default_factory=Counter)


def _groups(family: str, drafts: Sequence[Draft], selection: SelectionRule) -> list[list[Draft]]:
    if family == "weekly_upside":
        order = list(selection.upside_positions)
        keys = sorted(
            {d.position for d in drafts}, key=lambda p: (order.index(p) if p in order else 99, p)
        )
        return [[d for d in drafts if d.position == key] for key in keys]
    return [[d for d in drafts if d.variant == variant] for variant in VARIANTS[family]]


def _family_order(
    family: str,
    drafts: Sequence[Draft],
    rule: InsightRule,
    selection: SelectionRule,
    out: Selection,
) -> list[Draft]:
    groups = []
    for group in _groups(family, drafts, selection):
        ordered = sorted(group, key=lambda d: d.order)
        if len(ordered) > rule.variant_cap:
            out.suppressed[(family, "variant_cap")] += len(ordered) - rule.variant_cap
            ordered = ordered[: rule.variant_cap]
        for index, draft in enumerate(ordered, start=1):
            draft.family_rank = index
        groups.append(ordered)
    interleaved: list[Draft] = []
    depth = max((len(group) for group in groups), default=0)
    for index in range(depth):
        for group in groups:
            if index < len(group):
                interleaved.append(group[index])
    return interleaved


def select(
    drafts: Mapping[str, Sequence[Draft]],
    *,
    rule: InsightRule,
    selection: SelectionRule,
) -> Selection:
    out = Selection()
    ordered: dict[str, list[Draft]] = {
        family: _family_order(family, drafts.get(family, ()), rule, selection, out)
        for family in FAMILIES
    }
    owner: dict[str, Draft] = {}
    kept: dict[str, list[Draft]] = {family: [] for family in FAMILIES}
    for family in FAMILIES:
        for draft in ordered[family]:
            first = owner.get(draft.player_id)
            if first is not None:
                out.also.setdefault(first.story_id, []).append(draft.story_id)
                out.suppressed[(family, "duplicate_player")] += 1
                continue
            owner[draft.player_id] = draft
            kept[family].append(draft)
            out.stories.append(draft)

    family_count: Counter[str] = Counter()
    team_count: Counter[str] = Counter()
    pointer = dict.fromkeys(FAMILIES, 0)
    lead: list[Draft] = []
    progress = True
    while progress and len(lead) < selection.lead_max:
        progress = False
        for family in FAMILIES:
            if len(lead) >= selection.lead_max:
                break
            if family_count[family] >= selection.family_caps.get(family, 0):
                continue
            queue = kept[family]
            while pointer[family] < len(queue):
                draft = queue[pointer[family]]
                pointer[family] += 1
                if draft.team is not None and team_count[draft.team] >= selection.team_cap:
                    continue
                lead.append(draft)
                family_count[family] += 1
                if draft.team is not None:
                    team_count[draft.team] += 1
                progress = True
                break
    out.lead_rank = {draft.story_id: index for index, draft in enumerate(lead, start=1)}
    return out
