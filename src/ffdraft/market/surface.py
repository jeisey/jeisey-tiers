"""The public surface universe: who is visible, and why (Phase 10, ADR-063).

**Boundary module.** Market data decides *visibility* here and nothing else.

Release 1 published ``board.head(300)``. That single line was three decisions wearing one
number, and the failure it caused is the reason this module exists: a player the market was
drafting in the RB20-30 range could be absent from the public board, the status artifact and
every market comparison, simply because his intrinsic fair rank fell below 300 — with no
check anywhere that would notice.

`docs/RELEASE2_ROADMAP.md` 10.5 separates the three decisions, and this module implements
that separation:

1. **Intrinsic/model universe** — every eligible QB/RB/WR/TE the football-only model can
   value. Market-blind, unchanged, and not this module's business.
2. **Tier segmentation universe** — the contiguous fair-ranked prefix tiers are computed
   over. Versioned (:data:`TIER_DEPTH_RULE`), and contiguous by construction because a tier
   built from a market-filtered set would not be a tier.
3. **Public surface universe** — who is searchable and displayable, because either the
   model or current external evidence says he matters.

The rule that makes this safe is the one thing to keep in mind while reading:

    A market signal may change **whether a player is surfaced**. It may never change his
    projection, his VORP, his fair rank, or his tier.

A surfaced player from outside the tier depth therefore carries ``outside_tier_board=True``
and **no tier**, rather than being handed a fabricated one. He has a fair rank — the model
computed it — and that is exactly the number a reader needs to see next to a market price
that disagrees with it.

The vocabulary in :class:`~ffdraft.contracts.enums.SurfaceReason` is deliberately larger
than draft mode needs. Phase 12 has to surface a third-string back who became the starter in
week 6, and a contract that changes shape mid-season is a contract nobody trusts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.contracts import QualityCheck, SurfaceReason
from ffdraft.contracts.enums import MarketSignalType, Severity

__all__ = [
    "MARKET_TOP_DEPTH",
    "SURFACE_RULE_VERSION",
    "TIER_DEPTH_RULE",
    "MarketMembership",
    "SurfaceEntry",
    "SurfaceUniverse",
    "TierDepthRule",
    "build_surface_universe",
    "coverage_checks",
    "reason_for_source",
]

#: Bumped when the meaning of a surface decision changes. Travels on the artifact so a
#: board can be reproduced against the rule that produced it.
SURFACE_RULE_VERSION = "phase10_surface_v1"

#: How deep "the top of a market" reaches when deciding relevance.
#:
#: 300 is the roadmap's number and it is retained, but it is a *ceiling*, not an
#: expectation: Fantasy Football Calculator's entire published population is 221-264 rows
#: including kickers and defences, with a deepest ADP of 201.1 (measured 2026-09-02). For
#: that source "top 300" is the whole source, which is the correct reading — the rule asks
#: for the top of each market, not for a market to have 300 rows.
MARKET_TOP_DEPTH = 300


@dataclass(frozen=True, slots=True)
class TierDepthRule:
    """The versioned depth tier segmentation runs over.

    V1 froze 300 and Phase 4's evidence is recorded against it. Phase 10 does not rewrite
    that evidence: it declares a **new version** with a new depth, so a V1 board remains
    reproducible from the V1 rule (Release 2 guardrail 2.1).
    """

    version: str
    depth: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "depth": self.depth, "rationale": self.rationale}


#: V1, frozen. Kept so a Release 1 board can still be rebuilt exactly.
TIER_DEPTH_V1 = TierDepthRule(
    version="phase4_tier_depth_v1",
    depth=300,
    rationale=(
        "the deepest launch preset drafts 14 x 13 = 182 players, so 300 covered every pick "
        "with headroom"
    ),
)

#: V2, the Phase-10 depth. **A reasoned choice, not a measured optimum, and the difference
#: is recorded rather than papered over.**
#:
#: `scripts/phase10_depth_analysis.py` was written to measure this from the joined board and
#: found that it cannot: an arbitrage row exists only for a player already on the tier board,
#: so against a board published at depth 300 every "players beyond 300" count is zero **by
#: construction**. That is the wrong-denominator defect ADR-054 recorded elsewhere, and the
#: script now detects and refuses to conclude from it rather than reporting a confident zero.
#: Answering it properly needs the full intrinsic board joined against a market snapshot,
#: which means a production build with the retained store attached.
#:
#: What *is* measured and does bound the choice:
#:
#: * 300 is definitively too shallow. The roadmap's own motivating case - a back drafted
#:   around RB20-30 and absent from the 300-row board - is one market-priced player beyond
#:   it, and one is enough to prove the bound.
#: * FFC's entire published population is 221-264 rows with a deepest ADP of 201.1, so its
#:   contribution is bounded well inside any candidate here.
#: * The deepest launch preset drafts 14 x 13 = 182 players, so 500 is roughly 2.7x the
#:   deepest board anyone actually drafts.
#:
#: 500 is therefore the smallest simple value with real headroom over the only bound that is
#: measured. **The surface coverage gate is the safety net**, and it is a critical check: if
#: 500 is ever too shallow, a resolved top-market player fails the build rather than
#: disappearing quietly. That is the property that makes an unmeasured depth acceptable here
#: and would not have made the unguarded 300 acceptable.
TIER_DEPTH_V2 = TierDepthRule(
    version="phase10_tier_depth_v2",
    depth=500,
    rationale=(
        "the smallest simple depth with headroom over the one measured bound (300 is too "
        "shallow by the roadmap's own case); the joined distribution is unmeasurable from a "
        "truncated artifact, so the critical surface-coverage gate is the safety net"
    ),
)

#: The rule in force. Changing this is a versioned decision, not a tuning knob.
TIER_DEPTH_RULE = TIER_DEPTH_V2


#: Which surface reason a source's top-N membership produces. A source with no mapping
#: cannot silently invent one: :func:`reason_for_source` raises, because an unlabelled
#: surface reason is a row nobody can explain later.
_SOURCE_REASONS: dict[tuple[str, MarketSignalType], SurfaceReason] = {
    ("fantasyfootballcalculator_adp", MarketSignalType.ADP): (SurfaceReason.MARKET_TOP300_FFC_ADP),
    ("myfantasyleague_adp", MarketSignalType.ADP): SurfaceReason.MARKET_TOP300_MFL_ADP,
    ("fantasypros_adp", MarketSignalType.ADP): SurfaceReason.MARKET_TOP300_FANTASYPROS_ADP,
    ("fantasypros_ecr", MarketSignalType.ECR): SurfaceReason.MARKET_TOP300_FANTASYPROS_ECR,
}


def reason_for_source(source_id: str, signal_type: MarketSignalType) -> SurfaceReason:
    """The surface reason one source's top-N membership justifies."""
    reason = _SOURCE_REASONS.get((source_id, signal_type))
    if reason is None:
        raise ValueError(
            f"no surface reason declared for {source_id!r}/{signal_type}; a surfaced player "
            "must carry a reason a reader can interpret (roadmap 10.5)",
        )
    return reason


@dataclass(frozen=True, slots=True)
class MarketMembership:
    """One source's top-N population for one scoring preset.

    ``resolved`` holds canonical player ids. ``unresolved`` counts the source rows that did
    not reach a canonical player, and is reported **separately** — roadmap 10.5 is explicit
    that identity failures must not be hidden inside the coverage denominator, because that
    is precisely how a coverage number stays at 100% while players go missing.
    """

    source_id: str
    signal_type: MarketSignalType
    scoring_preset: str
    resolved: frozenset[str]
    unresolved: int = 0
    depth: int = MARKET_TOP_DEPTH

    @property
    def reason(self) -> SurfaceReason:
        return reason_for_source(self.source_id, self.signal_type)


@dataclass(frozen=True, slots=True)
class SurfaceEntry:
    """One player's place on the public surface."""

    player_id: str
    fair_rank: int
    reasons: tuple[SurfaceReason, ...]
    outside_tier_board: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "fair_rank": self.fair_rank,
            "surface_reasons": [str(reason) for reason in self.reasons],
            "outside_tier_board": self.outside_tier_board,
        }


@dataclass
class SurfaceUniverse:
    """Who is public for one (scoring preset, league preset), and why."""

    scoring_preset: str
    league_preset_id: str
    rule_version: str
    tier_depth: int
    entries: dict[str, SurfaceEntry] = field(default_factory=dict)
    memberships: tuple[MarketMembership, ...] = ()
    #: Resolved top-N players the surface could not include, with the reason. Non-empty is
    #: a build failure, not a warning: it is the 300-row blind spot recurring.
    missing: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tier_members(self) -> tuple[str, ...]:
        members = (
            entry.player_id for entry in self.entries.values() if not entry.outside_tier_board
        )
        return tuple(sorted(members, key=lambda pid: self.entries[pid].fair_rank))

    @property
    def exceptions(self) -> tuple[str, ...]:
        """Players surfaced by market relevance alone, in fair-rank order."""
        outside = (entry.player_id for entry in self.entries.values() if entry.outside_tier_board)
        return tuple(sorted(outside, key=lambda pid: self.entries[pid].fair_rank))

    @property
    def coverage(self) -> float:
        """Share of resolved top-N market players present on the surface."""
        wanted = {pid for membership in self.memberships for pid in membership.resolved}
        if not wanted:
            return 1.0
        return sum(1 for pid in wanted if pid in self.entries) / len(wanted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring_preset": self.scoring_preset,
            "league_preset_id": self.league_preset_id,
            "rule_version": self.rule_version,
            "tier_depth": self.tier_depth,
            "surfaced": len(self.entries),
            "tier_members": len(self.tier_members),
            "market_exceptions": len(self.exceptions),
            "market_top_depth": MARKET_TOP_DEPTH,
            "market_top300_surface_coverage": round(self.coverage, 6),
            "sources": [
                {
                    "source_id": membership.source_id,
                    "market_signal_type": str(membership.signal_type),
                    "surface_reason": str(membership.reason),
                    "resolved_top_players": len(membership.resolved),
                    # Measured separately, on purpose. An unresolved source row is an
                    # identity problem; hiding it in the coverage denominator would turn it
                    # into an invisible one.
                    "unresolved_source_rows": membership.unresolved,
                }
                for membership in self.memberships
            ],
            "missing": list(self.missing),
        }


def build_surface_universe(
    board: Sequence[Mapping[str, Any]],
    *,
    scoring_preset: str,
    league_preset_id: str,
    memberships: Iterable[MarketMembership] = (),
    tier_depth: int | None = None,
    rule_version: str = SURFACE_RULE_VERSION,
) -> SurfaceUniverse:
    """Decide the public surface from the fair-ranked board and the market's top rows.

    ``board`` is the **whole** intrinsic universe in fair-rank order, not a pre-truncated
    prefix. Passing the truncated board would reintroduce the bug: a player who is not in
    the input cannot be surfaced by any rule, however relevant the market says he is.
    """
    depth = tier_depth if tier_depth is not None else TIER_DEPTH_RULE.depth
    relevant = [m for m in memberships if m.scoring_preset == scoring_preset]
    universe = SurfaceUniverse(
        scoring_preset=scoring_preset,
        league_preset_id=league_preset_id,
        rule_version=rule_version,
        tier_depth=depth,
        memberships=tuple(sorted(relevant, key=lambda m: (m.source_id, str(m.signal_type)))),
    )

    ranked = sorted(board, key=lambda row: int(row["fair_rank"]))
    known: dict[str, int] = {str(row["player_id"]): int(row["fair_rank"]) for row in ranked}

    reasons_by_player: dict[str, list[SurfaceReason]] = {}
    for row in ranked:
        player_id = str(row["player_id"])
        if int(row["fair_rank"]) <= depth:
            reasons_by_player.setdefault(player_id, []).append(
                SurfaceReason.INTRINSIC_TOP_TIER_DEPTH,
            )

    for membership in universe.memberships:
        for player_id in sorted(membership.resolved):
            if player_id not in known:
                # The market prices a player the intrinsic model never valued. He cannot be
                # surfaced — there is no fair rank to show beside the price — and pretending
                # otherwise would put a row on the board with half its columns invented.
                universe.missing.append(
                    {
                        "player_id": player_id,
                        "source_id": membership.source_id,
                        "market_signal_type": str(membership.signal_type),
                        "reason": "absent_from_intrinsic_universe",
                    },
                )
                continue
            reasons_by_player.setdefault(player_id, []).append(membership.reason)

    for player_id, reasons in reasons_by_player.items():
        ordered = tuple(dict.fromkeys(sorted(reasons, key=str)))
        universe.entries[player_id] = SurfaceEntry(
            player_id=player_id,
            fair_rank=known[player_id],
            reasons=ordered,
            outside_tier_board=known[player_id] > depth,
        )
    return universe


def coverage_checks(universes: Sequence[SurfaceUniverse]) -> list[QualityCheck]:
    """The market-relevance coverage gate (roadmap 10.5).

    The required figure is **100%** of resolved top-N market rows, and the failure is
    critical rather than a warning. A warning is what the previous design effectively had:
    nothing looked, so nothing complained, and a drafted player was silently absent for the
    whole of the 2026 preseason.
    """
    checks: list[QualityCheck] = []
    for universe in universes:
        block = f"{universe.scoring_preset}/{universe.league_preset_id}"
        coverage = universe.coverage
        if coverage < 1.0 or universe.missing:
            sample = "; ".join(
                f"{item['player_id']} ({item['source_id']}: {item['reason']})"
                for item in universe.missing[:10]
            )
            checks.append(
                QualityCheck.fail(
                    "surface.market_top300_coverage",
                    stage="market.surface",
                    message=(
                        f"{block}: a resolved top-{MARKET_TOP_DEPTH} market player is not on "
                        "the public surface; this is the head(300) blind spot recurring"
                    ),
                    observed=f"{coverage:.1%} coverage, {len(universe.missing)} missing: {sample}",
                    expected="100% of resolved top-market rows surfaced",
                ),
            )
        else:
            checks.append(
                QualityCheck.ok(
                    "surface.market_top300_coverage",
                    stage="market.surface",
                    message=f"{block}: every resolved top-market player is publicly reachable",
                    observed=(
                        f"{len(universe.entries)} surfaced "
                        f"({len(universe.exceptions)} beyond tier depth {universe.tier_depth})"
                    ),
                ),
            )
        unresolved = sum(m.unresolved for m in universe.memberships)
        if unresolved:
            checks.append(
                QualityCheck.fail(
                    "surface.unresolved_market_rows",
                    stage="market.surface",
                    message=(
                        f"{block}: source rows that never reached a canonical player are "
                        "measured separately and are not inside the coverage denominator"
                    ),
                    observed=f"{unresolved} unresolved source row(s)",
                    expected="0, eventually; tracked rather than hidden",
                    severity=Severity.WARNING,
                ),
            )
    return checks
