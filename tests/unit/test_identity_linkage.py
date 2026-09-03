"""The FFC record-linkage rule (Phase 10, ADR-061).

These tests exist because `AGENTS.md` section 6 forbids a production join that depends
solely on normalized names, and the linkage is the one place this project comes close to
one. What makes it acceptable is that it *proposes* rather than decides, and that every
refusal is deliberate. So the tests are mostly about refusals: the cases where a plausible
answer exists and the rule must not take it.

The gold fixture is hand-checked and synthetic. Real names would make it a small
redistribution of a vendor's population and would rot as rosters change; invented names
exercise the same rules and stay valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffdraft.contracts import CanonicalPlayer, Position
from ffdraft.identity.linkage import (
    LINKAGE_RULE,
    LinkageRule,
    SourceRow,
    link_source_rows,
    linkage_key,
)
from ffdraft.identity.registry import CanonicalRegistry

GOLD_PATH = Path(__file__).parents[1] / "fixtures" / "identity" / "ffc_linkage_gold.json"
SOURCE_ID = "fantasyfootballcalculator_adp"


@pytest.fixture(scope="module")
def gold() -> dict:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry(gold: dict) -> CanonicalRegistry:
    players = {
        row["player_id"]: CanonicalPlayer(
            player_id=row["player_id"],
            display_name=row["display_name"],
            position=Position(row["position"]),
            team=row["team"],
        )
        for row in gold["canonical"]
    }
    return CanonicalRegistry(players=players, indexes={}, collisions={}, name_index={})


@pytest.fixture(scope="module")
def rows(gold: dict) -> list[dict]:
    return [case["row"] for case in gold["cases"]]


def _report(rows: list[dict], registry: CanonicalRegistry, rule: LinkageRule = LINKAGE_RULE):
    return link_source_rows(rows, registry=registry, source_id=SOURCE_ID, rule=rule)


def test_the_rule_version_the_gold_set_was_calibrated_against_is_still_in_force(gold: dict) -> None:
    """A threshold change must re-run the calibration, not silently inherit these answers."""
    assert LINKAGE_RULE.version == gold["rule_version"]


_CASE_IDS = [case["id"] for case in json.loads(GOLD_PATH.read_text(encoding="utf-8"))["cases"]]


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_every_gold_case_reaches_the_outcome_a_human_chose(
    case_id: str,
    gold: dict,
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    case = next(item for item in gold["cases"] if item["id"] == case_id)
    report = _report(rows, registry)
    external = case["row"]["external_player_id"]
    expected = case["expect"]

    accepted = {alias.external_player_id: alias for alias in report.accepted_rows}
    quarantined = {row.external_player_id: row for row in report.quarantine}
    excluded = {row.external_player_id: row for row in report.excluded}

    if expected["outcome"] == "accepted":
        assert external in accepted, f"{case_id}: {case['pins']}"
        alias = accepted[external]
        assert alias.player_id == expected["player_id"], case["pins"]
        assert alias.resolution_method == expected["method"], case["pins"]
        if "team_agrees" in expected:
            assert alias.team_agrees is expected["team_agrees"], case["pins"]
    elif expected["outcome"] == "quarantined":
        assert external in quarantined, f"{case_id}: {case['pins']}"
        row = quarantined[external]
        assert row.reason == expected["reason"], case["pins"]
        if "candidate_1_player_id" in expected:
            # A refusal still has to have looked at the right shortlist. Asserting the
            # top candidate is what proves the block worked, not just that nothing resolved.
            assert row.candidate_1_player_id == expected["candidate_1_player_id"], case["pins"]
    else:
        assert external in excluded, f"{case_id}: {case['pins']}"
        assert excluded[external].reason == expected["reason"], case["pins"]


def test_no_cross_position_candidate_can_ever_resolve(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """Position blocking is structural, so this holds for every accepted row at once."""
    report = _report(rows, registry)
    for alias in report.accepted_rows:
        canonical = registry.players[alias.player_id]
        assert str(canonical.position) == alias.position, (
            f"{alias.display_name} was accepted at {alias.position} but the canonical player "
            f"is a {canonical.position}"
        )


def test_normalization_never_collapses_two_distinct_players_into_one_alias(
    gold: dict,
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """The fixture deliberately contains two suffix-colliding RBs and two near-identical TEs."""
    report = _report(rows, registry)
    claimed = [alias.player_id for alias in report.accepted_rows]
    assert len(claimed) == len(set(claimed)), "two source rows resolved to the same player"

    colliding = [
        player["player_id"]
        for player in gold["canonical"]
        if player["position"] == "RB" and linkage_key(player["display_name"]) == "callum fitzwarren"
    ]
    assert len(colliding) == 2, "the fixture's collision pair is the point of this test"
    assert not (set(colliding) & set(claimed)), "a colliding canonical name produced an alias"


def test_output_is_deterministic_under_input_permutation(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    forward = _report(rows, registry)
    backward = _report(list(reversed(rows)), registry)
    assert [a.to_dict() for a in forward.accepted_rows] == [
        a.to_dict() for a in backward.accepted_rows
    ]
    assert [q.to_dict() for q in forward.quarantine] == [q.to_dict() for q in backward.quarantine]


def test_two_runs_produce_byte_identical_reports(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    first = json.dumps(_report(rows, registry).summary(), sort_keys=True)
    second = json.dumps(_report(rows, registry).summary(), sort_keys=True)
    assert first == second


def test_accepted_aliases_resolve_by_exact_id_without_rescoring(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """The alias file is the artifact; production capture looks up an id, it does not match.

    This is the property that makes a name-derived join acceptable at all: the fuzzy step
    happens once, is reviewable, and is never repeated for a player already in the file.
    """
    report = _report(rows, registry)
    entries = report.alias_entries(reviewed_by="test", reviewed_at="2026-09-02")
    by_external = {entry["external_id"]: entry for entry in entries}
    for alias in report.accepted_rows:
        entry = by_external[alias.external_player_id]
        assert entry["player_id"] == alias.player_id
        assert entry["source_id"] == SOURCE_ID
        # An alias entry carries only ids and a note - nothing a scorer would need.
        assert set(entry) == {
            "source_id",
            "external_id",
            "player_id",
            "reviewed_by",
            "reviewed_at",
            "note",
        }


def test_excluded_positions_stay_out_of_the_coverage_denominator(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    report = _report(rows, registry)
    assert len(report.excluded) == 2, "the fixture has one DEF and one PK"
    assert report.relevant == len(rows) - len(report.excluded)


def test_coverage_gate_and_top_unresolved_are_reported_separately(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """A 90% aggregate is not permission to lose a player the market drafts early."""
    report = _report(rows, registry)
    summary = report.summary()
    assert summary["coverage"] == pytest.approx(report.accepted / report.relevant)
    assert summary["min_coverage"] == 0.90
    # Every quarantined row in the fixture has an order key inside the top 300, so the
    # top-unresolved list must equal the quarantine rather than silently shrink.
    assert len(report.top_unresolved) == report.quarantined
    assert summary["top_unresolved"], "unresolved top rows must be listed, not just counted"


def test_candidate_recall_is_measured_against_the_gold_set(
    gold: dict,
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """Top-1 recall over the cases a human said have a correct answer.

    Recall is measured rather than asserted at 100%: the point is to notice a regression in
    candidate *generation*, which is a different failure from a threshold being too strict.
    """
    answerable = {
        case["row"]["external_player_id"]: case["expect"]["player_id"]
        for case in gold["cases"]
        if case["expect"]["outcome"] == "accepted"
    }
    report = _report(rows, registry)
    accepted = {alias.external_player_id: alias.player_id for alias in report.accepted_rows}
    hits = sum(1 for external, want in answerable.items() if accepted.get(external) == want)
    recall = hits / len(answerable)
    assert recall == 1.0, f"top-1 recall over the gold set fell to {recall:.1%}"


def test_a_permissive_threshold_would_have_accepted_the_ambiguous_pairs(
    registry: CanonicalRegistry,
    rows: list[dict],
) -> None:
    """The frozen thresholds are load-bearing, not decoration.

    Relaxing the margin to zero accepts rows the gold set marks ambiguous. Asserting that
    is what stops a future session raising the threshold "to improve coverage" without
    noticing which players it just guessed at.
    """
    permissive = LinkageRule(min_score=60.0, min_margin=0.0)
    loose = _report(rows, registry, permissive)
    strict = _report(rows, registry)
    assert loose.accepted > strict.accepted, (
        "loosening the rule accepted no extra rows, so the thresholds are not doing anything"
    )


def test_a_source_row_object_and_a_mapping_are_interchangeable(
    registry: CanonicalRegistry,
) -> None:
    mapping = {
        "external_player_id": "900",
        "display_name": "Tobias Vandermeer",
        "position": "QB",
        "team": "BUF",
        "order_key": 3.0,
    }
    typed = SourceRow(
        external_player_id="900",
        display_name="Tobias Vandermeer",
        position="QB",
        team="BUF",
        order_key=3.0,
    )
    assert (
        _report([mapping], registry).summary()
        == link_source_rows(
            [typed],
            registry=registry,
            source_id=SOURCE_ID,
        ).summary()
    )


def test_rows_without_an_order_key_get_no_rank_hint(registry: CanonicalRegistry) -> None:
    """A missing ADP is not rank 1, and an invented hint would misfile a review."""
    report = link_source_rows(
        [{"external_player_id": "901", "display_name": "Nobody Whatsoever", "position": "WR"}],
        registry=registry,
        source_id=SOURCE_ID,
    )
    assert report.quarantined == 1
    assert report.quarantine[0].rank_hint is None
    assert report.top_unresolved == []


# --------------------------------------------------------------------------------------
# The normalization rule itself
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ja'Marr Chase", "JaMarr Chase"),
        ("De\u2019Andre Hopkins", "DeAndre Hopkins"),
        ("Amon-Ra St. Brown", "Amon Ra St Brown"),
        ("Kyle Pitts Sr.", "Kyle Pitts"),
        ("Marvin Harrison Jr.", "Marvin Harrison"),
        ("Michael  Pittman", "Michael Pittman"),
        ("\u00c9mile Beaufort", "Emile Beaufort"),
        ("MARCUS DELACROIX", "marcus delacroix"),
    ],
)
def test_linkage_key_treats_two_spellings_of_one_name_as_equal(left: str, right: str) -> None:
    assert linkage_key(left) == linkage_key(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Jonah Wexley", "Jonas Wexley"),
        ("Rashad Bell", "Rashard Bell"),
        ("Michael Thomas", "Thomas"),
        ("Brian Robinson", "Bryan Robinson"),
    ],
)
def test_linkage_key_keeps_genuinely_different_names_apart(left: str, right: str) -> None:
    """Normalization must not be so eager that it merges two people."""
    assert linkage_key(left) != linkage_key(right)


def test_linkage_key_is_total_and_deterministic() -> None:
    assert linkage_key(None) == ""
    assert linkage_key("") == ""
    assert linkage_key("   ") == ""
    assert linkage_key("Ja'Marr Chase") == linkage_key("Ja'Marr Chase")
