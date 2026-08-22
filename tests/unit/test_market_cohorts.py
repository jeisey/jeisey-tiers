"""The frozen cohort sufficiency rule and its selection policy (ADR-039).

The rule was written before the measurement it decides, which is the only way an
evidence-driven threshold can mean anything. These tests pin the two properties that make
the policy honest rather than merely defensible:

* **specificity never beats sufficiency.** A cohort whose filter text exactly matches a
  preset but which prices forty players loses to the wider one.
* **approximation is allowed to be wide, never wrong.** A non-PPR cohort never serves a PPR
  league, a keeper-contaminated cohort never prices a redraft board (ADR-045), and HALF is
  never exact on a source that only knows a boolean.
"""

from __future__ import annotations

import pytest

from ffdraft.market.capture import PRODUCTION_COHORT_IDS
from ffdraft.market.cohorts import (
    CANDIDATE_COHORTS,
    COHORT_APPROXIMATE,
    COHORT_INSUFFICIENT,
    COHORT_SUFFICIENCY_RULE,
    CohortMeasurement,
    assignments_from_report,
    cohort_by_id,
    select_cohorts,
    widest_cohort,
)

LAUNCH_PRESETS = [(scoring, size) for size in (10, 12, 14) for scoring in ("STD", "HALF", "PPR")]


def measurement(cohort_id: str, **overrides) -> CohortMeasurement:
    """A comfortably sufficient cohort, with named clauses knocked out per test."""
    defaults: dict[str, object] = {
        "cohort_id": cohort_id,
        "filters": dict(cohort_by_id(cohort_id).filters),
        "priced_players": 320,
        "total_drafts": 500,
        "total_picks": 900,
        "resolved_players": 315,
        "resolvable_players": 320,
        "ambiguous_players": 0,
        "non_player_entities": 12,
        "top100_board_coverage": 0.99,
        "top150_board_coverage": 0.96,
        "median_top150_sample_size": 90.0,
        "min_pick_available": 320,
        "max_pick_available": 320,
        "adp_min": 1.2,
        "adp_max": 220.0,
        "total_rows": 340,
        "non_core_rows": 18,
        "unclassified_rows": 2,
    }
    defaults.update(overrides)
    return CohortMeasurement(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------


def test_a_healthy_cohort_passes_every_clause():
    verdict = COHORT_SUFFICIENCY_RULE.evaluate(measurement("unfiltered"))
    assert verdict.sufficient
    assert verdict.failed_clauses == ()


@pytest.mark.parametrize(
    ("override", "clause"),
    [
        ({"priced_players": 199}, "priced_players"),
        ({"total_drafts": 299}, "total_drafts"),
        ({"total_drafts": None}, "total_drafts"),
        ({"top100_board_coverage": 0.94}, "top100_board_coverage"),
        ({"top150_board_coverage": 0.89}, "top150_board_coverage"),
        ({"median_top150_sample_size": 24.0}, "median_top150_sample_size"),
        ({"median_top150_sample_size": None}, "median_top150_sample_size"),
        ({"resolved_players": 300, "resolvable_players": 320}, "identity_coverage"),
    ],
)
def test_each_clause_can_fail_on_its_own(override, clause):
    verdict = COHORT_SUFFICIENCY_RULE.evaluate(measurement("unfiltered", **override))
    assert not verdict.sufficient
    assert any(clause in failure for failure in verdict.failed_clauses)


def test_every_failing_clause_is_reported_not_just_the_first():
    """A cohort that fails four ways should say so once, not across four re-runs."""
    verdict = COHORT_SUFFICIENCY_RULE.evaluate(
        measurement(
            "std-fcount14",
            priced_players=0,
            total_drafts=2,
            top100_board_coverage=0.0,
            top150_board_coverage=0.0,
            median_top150_sample_size=None,
            resolved_players=0,
            resolvable_players=0,
        ),
    )
    assert not verdict.sufficient
    assert len(verdict.failed_clauses) == 6


def test_the_rule_is_pure_and_carries_its_version():
    rule = COHORT_SUFFICIENCY_RULE.to_dict()
    assert rule["rule_version"] == "phase5_cohort_v2"
    subject = measurement("ppr")
    assert COHORT_SUFFICIENCY_RULE.evaluate(subject) == COHORT_SUFFICIENCY_RULE.evaluate(subject)


# --------------------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------------------


def test_an_adequate_exact_cohort_wins():
    """Selection with the redraft requirement relaxed, so specificity is what is tested."""
    measurements = {
        "unfiltered": measurement("unfiltered"),
        "ppr": measurement("ppr"),
        "ppr-fcount12": measurement("ppr-fcount12"),
    }
    assignments, _ = select_cohorts(
        measurements,
        presets=[("PPR", 12)],
        require_redraft=False,
    )
    chosen = assignments[("PPR", 12)]
    assert chosen.cohort.cohort_id == "ppr-fcount12"
    assert chosen.exact is True
    assert chosen.quality_flags == ()


def test_a_thin_exact_cohort_loses_to_a_wider_reliable_one():
    """ADR-039: specificity never beats sufficiency."""
    measurements = {
        "unfiltered": measurement("unfiltered"),
        "ppr": measurement("ppr"),
        "ppr-fcount12": measurement("ppr-fcount12", priced_players=40, total_drafts=11),
    }
    assignments, verdicts = select_cohorts(
        measurements,
        presets=[("PPR", 12)],
        require_redraft=False,
    )
    assert verdicts["ppr-fcount12"].sufficient is False
    chosen = assignments[("PPR", 12)]
    assert chosen.cohort.cohort_id == "ppr"
    assert chosen.exact is False
    assert COHORT_APPROXIMATE in chosen.quality_flags


def test_the_widest_cohort_is_the_last_resort_and_is_flagged():
    measurements = {
        cohort_id: measurement(cohort_id, priced_players=5, total_drafts=2)
        for cohort_id in ("unfiltered", "ppr", "ppr-fcount12")
    }
    assignments, _ = select_cohorts(
        measurements,
        presets=[("PPR", 12)],
        require_redraft=False,
    )
    chosen = assignments[("PPR", 12)]
    assert chosen.cohort.cohort_id == widest_cohort().cohort_id
    assert chosen.sufficient is False
    assert set(chosen.quality_flags) == {COHORT_APPROXIMATE, COHORT_INSUFFICIENT}
    assert "no candidate met the sufficiency rule" in chosen.reason


def test_the_fallback_prefers_the_widest_qualifying_candidate_deterministically():
    """When nothing passes, "widest" means least specific, then most of the board priced."""
    measurements = {
        "no-keeper": measurement("no-keeper", priced_players=291, total_drafts=125),
        "no-mock-no-keeper": measurement(
            "no-mock-no-keeper",
            priced_players=250,
            total_drafts=125,
        ),
        "ppr-no-keeper": measurement("ppr-no-keeper", priced_players=300, total_drafts=115),
    }
    assignments, verdicts = select_cohorts(measurements, presets=[("PPR", 12)])
    assert not any(verdict.sufficient for verdict in verdicts.values())
    chosen = assignments[("PPR", 12)]
    assert chosen.cohort.cohort_id == "no-keeper"
    assert chosen.cohort.specificity == 0
    assert COHORT_INSUFFICIENT in chosen.quality_flags


# --------------------------------------------------------------------------------------
# The redraft requirement (ADR-045)
# --------------------------------------------------------------------------------------


def test_a_keeper_contaminated_cohort_can_never_price_a_redraft_board():
    """A dynasty rookie draft's "average pick" is a pick in a rookie-only draft."""
    measurements = {cohort.cohort_id: measurement(cohort.cohort_id) for cohort in CANDIDATE_COHORTS}
    assignments, _ = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    for assignment in assignments.values():
        assert assignment.cohort.excludes_keepers, assignment.cohort.cohort_id
        assert assignment.cohort.filters["IS_KEEPER"] == "N"


def test_the_requirement_is_qualifying_not_a_sufficiency_bound():
    """A keeper-free cohort still has to earn its way past every volume clause."""
    measurements = {
        "no-keeper": measurement("no-keeper", priced_players=10, total_drafts=3),
        "unfiltered": measurement("unfiltered"),
    }
    _assignments, verdicts = select_cohorts(measurements, presets=[("PPR", 12)])
    assert verdicts["no-keeper"].sufficient is False
    assert verdicts["unfiltered"].sufficient is True


def test_selection_raises_rather_than_pricing_a_board_with_nothing_valid():
    """Silently falling back to a contradicting cohort is the failure mode to avoid."""
    measurements = {"unfiltered": measurement("unfiltered")}
    with pytest.raises(ValueError, match="no cohort qualifies"):
        select_cohorts(measurements, presets=[("PPR", 12)])


def test_excludes_keepers_reads_the_filter_that_was_actually_sent():
    assert cohort_by_id("no-keeper").excludes_keepers is True
    assert cohort_by_id("no-mock-no-keeper").excludes_keepers is True
    assert cohort_by_id("ppr-no-keeper").excludes_keepers is True
    assert cohort_by_id("no-mock").excludes_keepers is False
    assert cohort_by_id("unfiltered").excludes_keepers is False
    assert cohort_by_id("ppr").excludes_keepers is False


def test_a_contradicting_cohort_never_serves_a_preset():
    """Approximation may be wide; it may not be wrong."""
    measurements = {
        "unfiltered": measurement("unfiltered"),
        "std": measurement("std"),
        "std-fcount12": measurement("std-fcount12"),
        "fcount14": measurement("fcount14"),
    }
    assignments, _ = select_cohorts(
        measurements,
        presets=[("PPR", 12)],
        require_redraft=False,
    )
    chosen = assignments[("PPR", 12)].cohort
    assert chosen.scoring_semantics is None
    assert chosen.league_size_semantics is None
    assert chosen.cohort_id == "unfiltered"


def test_half_ppr_can_never_be_exact():
    """MFL exposes IS_PPR as a boolean; there is no half-PPR filter to be exact about."""
    measurements = {cohort.cohort_id: measurement(cohort.cohort_id) for cohort in CANDIDATE_COHORTS}
    assignments, _ = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    for (scoring, _size), assignment in assignments.items():
        if scoring == "HALF":
            assert assignment.exact is False
            assert COHORT_APPROXIMATE in assignment.quality_flags
    assert all(cohort.scoring_semantics != "HALF" for cohort in CANDIDATE_COHORTS)


def test_every_launch_preset_gets_an_assignment():
    measurements = {cohort.cohort_id: measurement(cohort.cohort_id) for cohort in CANDIDATE_COHORTS}
    assignments, verdicts = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    assert set(assignments) == set(LAUNCH_PRESETS)
    assert set(verdicts) == {cohort.cohort_id for cohort in CANDIDATE_COHORTS}


def test_a_routine_production_capture_can_actually_price_every_launch_preset():
    """The set a daily capture retains must contain something the frozen rule can pick.

    This is the test that was missing, and its absence cost a production run. Every other
    selection test here hands `select_cohorts` measurements for *all sixteen* candidates,
    so all of them passed while `PRODUCTION_COHORT_IDS` held only keeper-contaminated
    cohorts — a set frozen under `phase5_cohort_v1`, before ADR-045 made a keeper-free
    cohort a qualifying condition for a redraft board. A production capture therefore
    retained nothing the rule could legally choose, and `select_cohorts` correctly refused
    to price a board. It failed closed, which is the design working; but it failed on every
    run, which is a capture-set bug.

    The fix is not to relax the rule. It is to retain what the rule needs.
    """
    measurements = {cohort_id: measurement(cohort_id) for cohort_id in PRODUCTION_COHORT_IDS}
    assignments, _ = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    assert set(assignments) == set(LAUNCH_PRESETS)
    for preset, assignment in assignments.items():
        assert assignment.cohort.excludes_keepers, (
            f"{preset} would be priced by {assignment.cohort.cohort_id}, which does not "
            "exclude keeper and dynasty drafts (ADR-045)"
        )


def test_the_production_capture_keeps_the_reference_the_keeper_finding_needs():
    """ADR-045 was found by *comparing* a keeper-free cohort against the aggregate.

    Retaining only the cohorts the rule picks would make that comparison unrepeatable, so
    the contaminated reference is captured on purpose. It can never be selected — it does
    not exclude keepers — which is exactly why keeping it costs nothing but bytes.
    """
    assert "unfiltered" in PRODUCTION_COHORT_IDS
    assert not cohort_by_id("unfiltered").excludes_keepers


def test_selection_is_deterministic_under_input_permutation():
    measurements = {cohort.cohort_id: measurement(cohort.cohort_id) for cohort in CANDIDATE_COHORTS}
    reversed_order = dict(reversed(list(measurements.items())))
    first, _ = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    second, _ = select_cohorts(reversed_order, presets=LAUNCH_PRESETS)
    assert {key: value.cohort.cohort_id for key, value in first.items()} == {
        key: value.cohort.cohort_id for key, value in second.items()
    }


# --------------------------------------------------------------------------------------
# Filters and serialization
# --------------------------------------------------------------------------------------


def test_filters_are_serialized_exactly_as_sent():
    assert cohort_by_id("ppr-fcount12").filters == {"IS_PPR": "1", "FCOUNT": "12"}
    assert cohort_by_id("ppr-fcount12").filter_query == "FCOUNT=12&IS_PPR=1"
    assert cohort_by_id("no-mock-no-keeper").filters == {"IS_MOCK": "0", "IS_KEEPER": "N"}


def test_every_candidate_uses_only_filters_phase_0_verified_as_honoured():
    """`DAYS` is ignored and `CUTOFF` has no effect; a candidate built on either would be
    a duplicate of the unfiltered aggregate wearing a label (docs/DATA_SOURCES.md 13.5)."""
    honoured = {"IS_PPR", "FCOUNT", "IS_MOCK", "IS_KEEPER"}
    for cohort in CANDIDATE_COHORTS:
        assert set(cohort.filters) <= honoured, cohort.cohort_id


def test_an_assignment_round_trips_through_a_committed_report():
    measurements = {cohort.cohort_id: measurement(cohort.cohort_id) for cohort in CANDIDATE_COHORTS}
    assignments, _ = select_cohorts(measurements, presets=LAUNCH_PRESETS)
    payload = {"assignments": [item.to_dict() for _, item in sorted(assignments.items())]}
    restored = assignments_from_report(payload)
    assert set(restored) == set(assignments)
    for key, item in assignments.items():
        assert restored[key].cohort.cohort_id == item.cohort.cohort_id
        assert restored[key].exact == item.exact
        assert restored[key].sufficient == item.sufficient
