"""The text the prospective workflow posts: progress always, the verdict only when taken."""

from __future__ import annotations

import prospective_report

STATUS = {
    "season": 2026,
    "weeks": 8,
    "rows": 9100,
    "pairs": 61000,
    "minimum": {"weeks": 8, "rows": 6000, "pairs": 40000},
    "complete_weeks": list(range(5, 13)),
    "captures": 40,
    "eligible": 12000,
    "due": "first",
    "taken": "first",
    "outcome": "insufficient_evidence",
    "closed": False,
}
VERDICT = {
    "outcome": "insufficient_evidence",
    "look": "first",
    "interval": {
        "difference": 0.0021,
        "lower": -0.0011,
        "upper": 0.0049,
        "weeks": 8,
        "level": 0.99,
    },
    "summary": {
        "v1": {
            "pinball": 1.1,
            "coverage_80": 0.81,
            "accuracy": 0.66,
            "brier": 0.21,
            "pairs": 61000,
        },
        "v2": {
            "pinball": 1.098,
            "coverage_80": 0.8,
            "accuracy": 0.661,
            "brier": 0.21,
            "pairs": 61000,
        },
    },
}


def test_a_taken_look_names_its_outcome_interval_and_what_happens_next() -> None:
    text = prospective_report.render(STATUS, VERDICT)
    assert "### The first look: **insufficient evidence**" in text
    assert "99% week-clustered interval [-0.00110, 0.00490] over 8 weeks" in text
    assert "which is not a rejection" in text
    assert "final look is taken automatically" in text
    assert "| v2 | 1.0980 | 0.800 | 0.6610 | 0.2100 | 61000 |" in text


def test_a_promotion_says_that_nothing_switches_by_itself() -> None:
    verdict = {**VERDICT, "outcome": "promote"}
    text = prospective_report.render({**STATUS, "outcome": "promote", "closed": True}, verdict)
    assert "Nothing switches by itself" in text


def test_progress_alone_shows_no_verdict() -> None:
    status = {**STATUS, "taken": None, "outcome": None, "due": None, "weeks": 3}
    text = prospective_report.render(status, None)
    assert "| weeks scored | 3 | 8 |" in text
    assert "No look was due." in text
    assert "pinball" not in text.lower()


def test_a_closed_evaluation_says_so() -> None:
    status = {"season": 2026, "closed": True, "taken": None, "recorded_looks": {"first": "reject"}}
    assert "closed" in prospective_report.render(status, None)
    assert "first: reject" in prospective_report.render(status, None)
