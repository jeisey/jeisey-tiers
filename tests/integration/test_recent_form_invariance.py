"""Recent form cannot move any value, rank, tier or season actual (ADR-113, AGENTS.md §8).

The structural half is `tests/contract/test_architecture_boundary.py`: no value-producing
module can import `ffdraft.signals.recent`, and it imports no market, ownership or behaviour
module. This is the behavioural half: the same fixture build with recent form withheld
publishes byte-identical records in every other artifact — season actuals included — and the
two runs differ in `recent_form`, so the test is not vacuous.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ffdraft.pipeline.fixture_pipeline import load_fixture_inputs, run_fixture_pipeline
from ffdraft.signals import recent

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pipeline"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


@pytest.fixture(scope="module")
def enabled():
    return run_fixture_pipeline(load_fixture_inputs(FIXTURES))


@pytest.fixture(scope="module")
def disabled():
    patch = pytest.MonkeyPatch()

    def withheld(**kwargs: Any) -> recent.RecentFormResult:
        return recent.RecentFormResult(records=[], metadata={}, checks=[])

    patch.setattr(recent, "build_recent_form", withheld)
    try:
        return run_fixture_pipeline(load_fixture_inputs(FIXTURES))
    finally:
        patch.undo()


def test_the_comparison_is_not_vacuous(enabled, disabled):
    assert enabled.records.get("recent_form")
    assert "recent_form" not in disabled.records
    assert enabled.ros_build_metadata["recent_form"]["status"] == "published"


def test_every_other_artifact_is_byte_identical(enabled, disabled):
    others = set(enabled.records) - {"recent_form"}
    assert others == set(disabled.records)
    for artifact in sorted(others):
        assert _canonical(enabled.records[artifact]) == _canonical(
            disabled.records[artifact],
        ), artifact


def test_metadata_differs_only_in_the_recent_form_block(enabled, disabled):
    assert _canonical(enabled.build_metadata) == _canonical(disabled.build_metadata)
    # ADR-116: Insights reads recent form (the streak family), so its block says what it lost.
    skip = {"recent_form", "insights"}
    left = {k: v for k, v in enabled.ros_build_metadata.items() if k not in skip}
    right = {k: v for k, v in disabled.ros_build_metadata.items() if k not in skip}
    assert _canonical(left) == _canonical(right)
    families = disabled.ros_build_metadata["insights"]["families"]
    assert families["streak_watch"]["status"] == "unavailable"
    assert families["streak_watch"]["reason"] == "recent form is withheld for this build"
