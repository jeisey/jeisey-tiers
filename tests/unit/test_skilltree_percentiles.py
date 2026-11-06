"""The Skill Tree percentile audit (ADR-107 convention, ADR-117 audit), on real and edge cases.

Two implementations are held to one convention and to the published numbers:

* the builder's ``percentile_ranks`` (bisection over integers scaled at the published
  precision), which produced every published rank;
* the validator's own ``rederive_ranks`` (pairwise counts over the values as published, exact
  rationals), which checks them — independent on purpose, so a defect in the builder cannot
  validate itself.

The convention, unchanged: competition rank in the metric's direction, and
``100 × (strictly behind + (ties − 1) / 2) ÷ (cohort − 1)`` rounded to one place. A unique last
is 0, a unique first is 100, tied players share one value, and a tied *last* group is above 0.

The real cases are the owner's report. Dameon Pierce (``gsis:00-0037258``), RB yards per carry:
96 yards on 37 carries (nflverse weekly stats, weeks 5-7 with PHI: 11/14, 12/35, 14/47) = 2.59.
On the 2026-10-28 build (through week 7) he was the unique last of 60 qualified backs (25+
carries): rank 60, percentile 0.0. On the 2026-11-06 build (through week 8) his reading is
unchanged but Josh Jacobs (75 on 32 = 2.34) crossed the minimum below him: rank 65 of 66,
percentile 100 × 1 / 65 = 1.5. The fixtures are those two published cohorts, verbatim.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from ffdraft.artifacts.skilltree_checks import (
    percentile_agrees,
    rederive_ranks,
    skilltree_cross_checks,
)
from ffdraft.contracts.quality import CheckStatus
from ffdraft.signals.skilltree import MIN_COHORT, percentile_ranks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skill_tree"
PIERCE = "gsis:00-0037258"
JACOBS = "gsis:00-0035700"


def _cohort(tag: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"rb_yards_per_carry_{tag}.json").read_text(encoding="utf-8"))


def _ranked(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in cohort["rows"] if row["state"] == "ranked"]


# ----------------------------------------------------------------------- the reported case


@pytest.mark.parametrize(
    ("tag", "expected_rank", "expected_percentile", "size"),
    [("2026w07", 60, 0.0, 60), ("2026w08", 65, 1.5, 66)],
)
def test_pierce_reproduces_from_the_published_cohort(
    tag: str,
    expected_rank: int,
    expected_percentile: float,
    size: int,
) -> None:
    cohort = _cohort(tag)
    ranked = _ranked(cohort)
    assert len(ranked) == size
    pierce = next(row for row in cohort["rows"] if row["player_id"] == PIERCE)
    # The published sample and its arithmetic: 96 / 37 = 2.5946, published at 2 places.
    assert (pierce["numerator"], pierce["denominator"]) == (96, 37)
    assert pierce["value"] == round(96 / 37, 2) == 2.59
    assert (pierce["rank"], pierce["percentile"], pierce["cohort_size"]) == (
        expected_rank,
        expected_percentile,
        size,
    )
    # Every qualified back has at least the 25-carry minimum; every unqualified one has fewer.
    assert all(row["denominator"] >= cohort["minimum_carries"] for row in ranked)
    assert all(
        row["denominator"] < cohort["minimum_carries"]
        for row in cohort["rows"]
        if row["state"] == "below_minimum"
    )

    values = {row["player_id"]: row["value"] for row in ranked}
    builder = percentile_ranks(values, direction="higher", decimals=cohort["decimals"])
    validator = rederive_ranks(values, direction="higher")
    for row in ranked:
        published = (row["rank"], row["percentile"])
        assert builder[row["player_id"]] == published, row["player_id"]
        rank, exact = validator[row["player_id"]]
        assert rank == row["rank"] and percentile_agrees(row["percentile"], exact)


def test_the_cohort_changed_between_builds_not_his_reading() -> None:
    before, after = _cohort("2026w07"), _cohort("2026w08")
    reading = {
        tag: next(row for row in cohort["rows"] if row["player_id"] == PIERCE)
        for tag, cohort in (("before", before), ("after", after))
    }
    assert reading["before"]["value"] == reading["after"]["value"] == 2.59
    joined = {row["player_id"] for row in _ranked(after)} - {
        row["player_id"] for row in _ranked(before)
    }
    below_him = [
        row for row in _ranked(after) if row["player_id"] in joined and row["value"] < 2.59
    ]
    # Exactly one newly qualified back sits below him: Jacobs, now the unique last.
    assert [row["player_id"] for row in below_him] == [JACOBS]
    jacobs = below_him[0]
    assert (jacobs["numerator"], jacobs["denominator"], jacobs["value"]) == (75, 32, 2.34)
    assert (jacobs["rank"], jacobs["percentile"]) == (66, 0.0)
    # 100 x (1 behind + 0) / 65 = 1.538..., published at one place.
    assert reading["after"]["percentile"] == round(100 / 65, 1) == 1.5


def test_real_cohorts_contain_ties_that_share_rank_and_percentile() -> None:
    for tag in ("2026w07", "2026w08"):
        by_value: dict[float, list[dict[str, Any]]] = {}
        for row in _ranked(_cohort(tag)):
            by_value.setdefault(row["value"], []).append(row)
        tied = [rows for rows in by_value.values() if len(rows) > 1]
        assert tied, tag
        for rows in tied:
            assert len({(row["rank"], row["percentile"]) for row in rows}) == 1


# ------------------------------------------------------------------------------ the edges


def _both(values: dict[str, float], direction: str = "higher", decimals: int = 2):
    builder = percentile_ranks(values, direction=direction, decimals=decimals)
    validator = {
        key: (rank, float(round(exact, 1)))
        for key, (rank, exact) in rederive_ranks(
            {key: round(value, decimals) for key, value in values.items()},
            direction=direction,
        ).items()
    }
    return builder, validator


def test_unique_extremes_are_exactly_0_and_100() -> None:
    builder, validator = _both({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0})
    for ranks in (builder, validator):
        assert ranks["a"] == (1, 100.0)
        assert ranks["e"] == (5, 0.0)
        assert ranks["c"] == (3, 50.0)


def test_a_tied_last_group_is_above_zero_and_shares_one_rank() -> None:
    # Two tied at the bottom of six: rank 5 each, 100 x (0 + 1/2) / 5 = 10.
    values = {"a": 9.0, "b": 8.0, "c": 7.0, "d": 6.0, "e": 1.0, "f": 1.0}
    builder, validator = _both(values)
    for ranks in (builder, validator):
        assert ranks["e"] == ranks["f"] == (5, 10.0)
        assert ranks["d"] == (4, 40.0)
    # A tie at the top: rank 1 each, below 100.
    builder, _ = _both({"a": 9.0, "b": 9.0, "c": 7.0, "d": 6.0, "e": 1.0})
    assert builder["a"] == builder["b"] == (1, 87.5)


def test_lower_is_better_reverses_rank_and_percentile_once() -> None:
    values = {"fast": 4.31, "mid": 4.45, "mid2": 4.50, "slow": 4.62, "slowest": 4.70}
    builder, validator = _both(values, direction="lower")
    for ranks in (builder, validator):
        assert ranks["fast"] == (1, 100.0)
        assert ranks["slowest"] == (5, 0.0)


def test_values_that_publish_alike_tie() -> None:
    # 2.594 and 2.586 both publish as 2.59, so they are one value on the page and in the rank.
    values = {"a": 2.594, "b": 2.586, "c": 3.0, "d": 2.0, "e": 1.0}
    builder, validator = _both(values)
    for ranks in (builder, validator):
        assert ranks["a"] == ranks["b"] == (2, 62.5)


def test_an_insufficient_cohort_ranks_no_one_and_five_is_enough() -> None:
    assert MIN_COHORT == 5
    four = {"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}
    assert percentile_ranks(four, direction="higher", decimals=2) == {}
    assert rederive_ranks(four, direction="higher") == {}
    five = {**four, "e": 0.0}
    assert len(percentile_ranks(five, direction="higher", decimals=2)) == 5
    assert len(rederive_ranks(five, direction="higher")) == 5
    assert rederive_ranks({"a": 1.0}, direction="higher", min_cohort=0) == {}


def test_the_validator_agrees_within_half_a_published_unit_only() -> None:
    assert percentile_agrees(1.5, Fraction(100, 65))
    assert not percentile_agrees(1.6, Fraction(100, 65))
    assert not percentile_agrees(None, Fraction(0))
    assert not percentile_agrees(True, Fraction(1))


# ---------------------------------------------- the validator catches a wrong published rank


def _envelopes(tag: str, mutate=None) -> dict[str, dict[str, Any]]:
    """A one-metric tree from a real cohort, enough for the rank re-derivation."""
    cohort = _cohort(tag)
    records = []
    for row in cohort["rows"]:
        record = {
            "player_id": row["player_id"],
            "position": "RB",
            "metric_id": "yards_per_carry",
            "state": row["state"],
            "value": row["value"],
            "numerator": row["numerator"],
            "denominator": row["denominator"],
            "rank": row["rank"],
            "percentile": row["percentile"],
            "cohort_size": row["cohort_size"],
            "games": 3,
            "source_season": None,
            "reason": None,
        }
        records.append(record)
    if mutate is not None:
        mutate(records)
    definition = {
        "position": "RB",
        "metric_id": "yards_per_carry",
        "role": "node",
        "kind": "rate",
        "direction": "higher",
        "decimals": 2,
        "source_id": "player_stats",
    }
    return {
        "player_skill_tree": {"records": records},
        "skill_tree_definitions": {"records": [definition]},
    }


def _rank_failures(envelopes: dict[str, dict[str, Any]]) -> list[str]:
    return [
        check.observed
        for check in skilltree_cross_checks(envelopes)
        if check.check_id == "player_skill_tree.rank_rederivation"
        and check.status != CheckStatus.PASS
    ]


def test_the_validator_passes_the_published_cohorts() -> None:
    for tag in ("2026w07", "2026w08"):
        assert _rank_failures(_envelopes(tag)) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("rank", 59), ("percentile", 1.7), ("percentile", 0.1), ("cohort_size", 59)],
)
def test_the_validator_catches_one_wrong_published_number(field: str, value: Any) -> None:
    def corrupt(records: list[dict[str, Any]]) -> None:
        next(record for record in records if record["player_id"] == PIERCE)[field] = value

    failures = _rank_failures(_envelopes("2026w07", corrupt))
    assert failures and PIERCE in failures[0]
