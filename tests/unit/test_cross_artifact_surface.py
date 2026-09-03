"""The tiers/arbitrage subset rule, and the one row that is allowed to break it.

`cross_artifact.arbitrage_player_not_in_tiers` says every arbitrage row must describe a
player the tier artifact publishes. That was true for the whole of Release 1 and it stopped
being true the moment the surface rule was wired into production: a player the market drafts
early and the model ranks past the published tier depth is *deliberately* on the arbitrage
board and *deliberately* absent from tiers (ADR-063). The first production build after that
wiring failed this check on ten such players, which is the run these tests reproduce.

The exemption has to stay narrow. The failure the check was written for — an arbitrage row
for a player the board has no valuation for at all, half its columns invented — is still a
critical stop, and a row only escapes it by *declaring* itself an exception in both fields.
"""

from __future__ import annotations

from typing import Any

from ffdraft.artifacts.validate import _cross_artifact_checks

BLOCK = {"league_preset_id": "redraft-10", "scoring_preset": "HALF"}


def tier_row(player_id: str, fair_rank: int) -> dict[str, Any]:
    return {**BLOCK, "player_id": player_id, "fair_rank": fair_rank}


def arb_row(player_id: str, fair_rank: int, **extra: Any) -> dict[str, Any]:
    return {**BLOCK, "player_id": player_id, "fair_rank": fair_rank, **extra}


def check(tiers: list[dict[str, Any]], arbitrage: list[dict[str, Any]]) -> dict[str, str]:
    checks = _cross_artifact_checks(
        {"tiers": {"records": tiers}, "arbitrage": {"records": arbitrage}},
    )
    return {c.check_id: c.status for c in checks}


def test_a_surfaced_player_may_be_absent_from_tiers() -> None:
    """The production failure of 2026-09-03, and the behaviour that fixes it.

    `gsis:00-0039344` is priced by the market and ranked past the published tier depth. He
    belongs on the arbitrage board flagged as outside it; requiring him to be a tier row too
    would forbid exactly the rescue the surface rule exists to perform.
    """
    results = check(
        [tier_row("gsis:001", 1)],
        [
            arb_row("gsis:001", 1),
            arb_row(
                "gsis:00-0039344",
                640,
                outside_tier_board=True,
                surface_reasons=["market_top300_ffc_adp"],
            ),
        ],
    )

    assert "cross_artifact.arbitrage_player_not_in_tiers" not in results
    assert results["cross_artifact.agreement"] == "pass"


def test_an_undeclared_absence_is_still_a_critical_stop() -> None:
    """The failure the rule was written for is untouched.

    A row that is simply missing from tiers, with no claim to be an exception, is an
    arbitrage record describing a player the board never valued. That has always been a
    build failure and still is.
    """
    results = check([tier_row("gsis:001", 1)], [arb_row("gsis:002", 900)])

    assert results["cross_artifact.arbitrage_player_not_in_tiers"] == "fail"


def test_half_a_declaration_does_not_earn_the_exemption() -> None:
    """Both fields, or neither. One alone is as likely a serialization bug as a decision."""
    only_flag = check(
        [tier_row("gsis:001", 1)], [arb_row("gsis:002", 900, outside_tier_board=True)]
    )
    only_reasons = check(
        [tier_row("gsis:001", 1)],
        [arb_row("gsis:002", 900, surface_reasons=["market_top300_ffc_adp"])],
    )

    assert only_flag["cross_artifact.arbitrage_player_not_in_tiers"] == "fail"
    assert only_reasons["cross_artifact.arbitrage_player_not_in_tiers"] == "fail"


def test_a_player_on_the_board_may_not_claim_to_be_beyond_it() -> None:
    """The inverse lie, which the old subset rule could never have caught.

    A row flagged `outside_tier_board` while the tier artifact publishes him would render a
    surface-exception badge on an ordinary board member. Cheap to detect once the exemption
    exists, and worth detecting: the exemption is the only thing that makes it reachable.
    """
    results = check(
        [tier_row("gsis:001", 1)],
        [
            arb_row(
                "gsis:001",
                1,
                outside_tier_board=True,
                surface_reasons=["market_top300_ffc_adp"],
            ),
        ],
    )

    assert results["cross_artifact.surface_exception_is_on_the_board"] == "fail"


def test_fair_rank_must_still_agree_for_an_ordinary_row() -> None:
    """Unrelated to the exemption, and easy to break while adding one."""
    results = check([tier_row("gsis:001", 1)], [arb_row("gsis:001", 2)])

    assert results["cross_artifact.fair_rank_disagreement"] == "fail"
