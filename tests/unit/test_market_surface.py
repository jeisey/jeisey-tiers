"""The public surface universe and the 300-row blind spot (Phase 10, ADR-063).

The regression test the roadmap asks for is
:func:`test_a_market_relevant_player_below_the_tier_depth_cannot_disappear`. Everything
else here exists to stop that fix being undone by a well-meaning simplification: the
separation of the three universes only works if visibility and valuation stay separate, and
each of those properties is asserted rather than assumed.
"""

from __future__ import annotations

import pytest

from ffdraft.contracts import SurfaceReason
from ffdraft.contracts.enums import MarketSignalType
from ffdraft.market.surface import (
    MARKET_TOP_DEPTH,
    TIER_DEPTH_RULE,
    TIER_DEPTH_V1,
    TIER_DEPTH_V2,
    MarketMembership,
    build_surface_universe,
    coverage_checks,
    reason_for_source,
)

FFC = "fantasyfootballcalculator_adp"
MFL = "myfantasyleague_adp"


def board(size: int = 900) -> list[dict]:
    """The whole intrinsic universe in fair-rank order, which is what the rule needs."""
    return [{"player_id": f"gsis:{index:05d}", "fair_rank": index} for index in range(1, size + 1)]


def membership(
    *,
    source_id: str = FFC,
    players: set[str],
    scoring: str = "HALF",
    signal: MarketSignalType = MarketSignalType.ADP,
    unresolved: int = 0,
) -> MarketMembership:
    return MarketMembership(
        source_id=source_id,
        signal_type=signal,
        scoring_preset=scoring,
        resolved=frozenset(players),
        unresolved=unresolved,
    )


def build(memberships=(), *, depth: int | None = None, rows: list[dict] | None = None):
    return build_surface_universe(
        rows if rows is not None else board(),
        scoring_preset="HALF",
        league_preset_id="redraft-12",
        memberships=memberships,
        tier_depth=depth,
    )


# --------------------------------------------------------------------------------------
# The regression the roadmap requires
# --------------------------------------------------------------------------------------


def test_a_market_relevant_player_below_the_tier_depth_cannot_disappear() -> None:
    """The `head(300)` blind spot, reproduced as a test so it cannot recur.

    A player the market drafts inside its own top rows, whose intrinsic fair rank is far
    below the tier depth, was invisible in Release 1: absent from the board, the status
    artifact and every market comparison, with nothing anywhere that would notice. He must
    now be surfaced, carry the reason he was surfaced, and carry no tier.
    """
    deep_player = "gsis:00640"
    universe = build([membership(players={deep_player})], depth=500)

    assert deep_player in universe.entries, "the blind spot has recurred"
    entry = universe.entries[deep_player]
    assert entry.outside_tier_board is True
    assert SurfaceReason.MARKET_TOP300_FFC_ADP in entry.reasons
    assert SurfaceReason.INTRINSIC_TOP_TIER_DEPTH not in entry.reasons
    assert entry.fair_rank == 640, "his fair rank is the model's, unchanged"

    checks = coverage_checks([universe])
    coverage = next(c for c in checks if c.check_id == "surface.market_top300_coverage")
    assert coverage.status == "pass"
    assert universe.coverage == 1.0


def test_the_old_truncated_board_would_fail_the_gate() -> None:
    """Proof the gate is load-bearing: feed it the pre-truncated board and it must fail.

    This is the shape of the Release 1 bug — the deep player is not in the input at all —
    and a rule that quietly tolerated it would be the same defect wearing new code.
    """
    truncated = board(300)
    universe = build([membership(players={"gsis:00640"})], depth=300, rows=truncated)

    assert universe.coverage < 1.0
    assert universe.missing and universe.missing[0]["reason"] == "absent_from_intrinsic_universe"
    failure = next(
        c for c in coverage_checks([universe]) if c.check_id == "surface.market_top300_coverage"
    )
    assert failure.status == "fail"
    assert failure.severity == "critical", "a silently missing drafted player is not a warning"


# --------------------------------------------------------------------------------------
# Visibility never touches valuation
# --------------------------------------------------------------------------------------


def test_market_membership_changes_visibility_and_nothing_else() -> None:
    """The invariant the whole design rests on."""
    plain = build()
    with_market = build([membership(players={"gsis:00640", "gsis:00042"})])

    for player_id, entry in plain.entries.items():
        assert with_market.entries[player_id].fair_rank == entry.fair_rank
    # The extra entry is the only difference, and it is an addition.
    assert set(with_market.entries) - set(plain.entries) == {"gsis:00640"}


def test_a_surfaced_exception_never_receives_a_tier() -> None:
    universe = build([membership(players={"gsis:00801"})], depth=500)
    assert universe.entries["gsis:00801"].outside_tier_board is True
    assert "gsis:00801" not in universe.tier_members
    assert universe.exceptions == ("gsis:00801",)


def test_tier_members_are_a_contiguous_fair_ranked_prefix() -> None:
    """A tier built from a market-filtered set would not be a tier."""
    universe = build([membership(players={"gsis:00640"})], depth=500)
    ranks = [universe.entries[pid].fair_rank for pid in universe.tier_members]
    assert ranks == list(range(1, 501))


# --------------------------------------------------------------------------------------
# Reasons and accounting
# --------------------------------------------------------------------------------------


def test_every_surfaced_player_carries_at_least_one_machine_readable_reason() -> None:
    universe = build([membership(players={"gsis:00640"})])
    for entry in universe.entries.values():
        assert entry.reasons
        assert all(isinstance(reason, SurfaceReason) for reason in entry.reasons)


def test_a_player_inside_the_depth_and_in_a_market_carries_both_reasons() -> None:
    universe = build([membership(players={"gsis:00042"})], depth=500)
    reasons = universe.entries["gsis:00042"].reasons
    assert SurfaceReason.INTRINSIC_TOP_TIER_DEPTH in reasons
    assert SurfaceReason.MARKET_TOP300_FFC_ADP in reasons


def test_two_sources_each_contribute_their_own_reason() -> None:
    universe = build(
        [
            membership(source_id=FFC, players={"gsis:00700"}),
            membership(source_id=MFL, players={"gsis:00700"}),
        ],
        depth=500,
    )
    reasons = universe.entries["gsis:00700"].reasons
    assert SurfaceReason.MARKET_TOP300_FFC_ADP in reasons
    assert SurfaceReason.MARKET_TOP300_MFL_ADP in reasons


def test_reasons_are_ordered_deterministically() -> None:
    forward = build(
        [
            membership(source_id=FFC, players={"gsis:00700"}),
            membership(source_id=MFL, players={"gsis:00700"}),
        ],
    )
    backward = build(
        [
            membership(source_id=MFL, players={"gsis:00700"}),
            membership(source_id=FFC, players={"gsis:00700"}),
        ],
    )
    assert forward.entries["gsis:00700"].reasons == backward.entries["gsis:00700"].reasons
    assert forward.to_dict() == backward.to_dict()


def test_an_undeclared_source_cannot_produce_an_unlabelled_reason() -> None:
    """A surfaced player whose reason nobody can interpret is worse than an error."""
    with pytest.raises(ValueError, match="no surface reason declared"):
        reason_for_source("some_new_vendor", MarketSignalType.ADP)


def test_unresolved_source_rows_are_reported_outside_the_coverage_denominator() -> None:
    """Roadmap 10.5: an identity failure must not be hidden inside a coverage number."""
    universe = build([membership(players={"gsis:00042"}, unresolved=17)])
    assert universe.coverage == 1.0, "coverage measures resolved rows only"

    checks = coverage_checks([universe])
    assert (
        next(c for c in checks if c.check_id == "surface.market_top300_coverage").status == "pass"
    )
    unresolved = next(c for c in checks if c.check_id == "surface.unresolved_market_rows")
    assert unresolved.status == "fail"
    assert unresolved.severity == "warning"
    assert "17" in unresolved.observed

    payload = universe.to_dict()
    assert payload["sources"][0]["unresolved_source_rows"] == 17
    assert payload["market_top300_surface_coverage"] == 1.0


def test_memberships_for_another_scoring_preset_are_ignored() -> None:
    universe = build([membership(players={"gsis:00640"}, scoring="PPR")])
    assert "gsis:00640" not in universe.entries
    assert universe.memberships == ()


def test_ecr_membership_uses_its_own_reason() -> None:
    """An expert consensus can make a player visible; it is still not an ADP."""
    universe = build(
        [
            membership(
                source_id="fantasypros_ecr",
                players={"gsis:00700"},
                signal=MarketSignalType.ECR,
            ),
        ],
    )
    reasons = universe.entries["gsis:00700"].reasons
    assert reasons == (SurfaceReason.MARKET_TOP300_FANTASYPROS_ECR,)


# --------------------------------------------------------------------------------------
# The versioned depth
# --------------------------------------------------------------------------------------


def test_v1_depth_is_preserved_so_a_release_1_board_stays_reproducible() -> None:
    """Release 2 guardrail 2.1: do not rewrite V1 evidence, version alongside it."""
    assert TIER_DEPTH_V1.depth == 300
    assert TIER_DEPTH_V1.version == "phase4_tier_depth_v1"
    assert TIER_DEPTH_V2.version != TIER_DEPTH_V1.version
    assert TIER_DEPTH_RULE is TIER_DEPTH_V2


def test_the_depth_in_force_is_deeper_than_v1_and_states_its_evidence() -> None:
    assert TIER_DEPTH_RULE.depth > TIER_DEPTH_V1.depth
    assert TIER_DEPTH_RULE.rationale.strip(), "a depth without a recorded reason is a guess"


def test_the_universe_records_the_rule_it_was_built_under() -> None:
    universe = build()
    payload = universe.to_dict()
    assert payload["tier_depth"] == TIER_DEPTH_RULE.depth
    assert payload["rule_version"]
    assert payload["market_top_depth"] == MARKET_TOP_DEPTH
