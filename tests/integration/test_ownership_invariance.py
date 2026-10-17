"""ESPN ownership cannot move any board value (ADR-112, AGENTS.md section 8).

The structural half is `tests/contract/test_architecture_boundary.py`: no value-producing
module can import the ownership package. This is the behavioural half: the same fixture
build with and without ESPN publishes byte-identical records in every other artifact,
including the intrinsic tiers, the rest-of-season board, projections, replacement-derived
VORP and the Opportunity Board — and the two runs differ in ESPN's artifacts, so the test
is not vacuous.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ffdraft.ownership.publish import OwnershipLayer
from ffdraft.pipeline import fixture_pipeline
from ffdraft.pipeline.fixture_pipeline import load_fixture_inputs, run_fixture_pipeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pipeline"
ESPN = {"espn_ownership", "espn_ownership_series"}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


@pytest.fixture(scope="module")
def with_espn():
    return run_fixture_pipeline(load_fixture_inputs(FIXTURES))


@pytest.fixture(scope="module")
def without_espn():
    patch = pytest.MonkeyPatch()
    patch.setattr(
        fixture_pipeline,
        "_espn_ownership_layer",
        lambda *args, **kwargs: OwnershipLayer(),
    )
    try:
        return run_fixture_pipeline(load_fixture_inputs(FIXTURES))
    finally:
        patch.undo()


def test_the_comparison_is_not_vacuous(with_espn, without_espn):
    assert set(with_espn.records) >= ESPN
    assert not ESPN & set(without_espn.records)
    assert with_espn.ros_build_metadata["espn_ownership"]["status"] == "published"
    assert without_espn.ros_build_metadata["espn_ownership"] is None


def test_every_other_artifact_is_byte_identical(with_espn, without_espn):
    others = set(with_espn.records) - ESPN
    assert others == set(without_espn.records)
    for artifact in sorted(others):
        assert _canonical(with_espn.records[artifact]) == _canonical(
            without_espn.records[artifact],
        ), artifact


def test_both_metadata_objects_differ_only_in_the_espn_block(with_espn, without_espn):
    assert _canonical(with_espn.build_metadata) == _canonical(without_espn.build_metadata)
    left = {k: v for k, v in with_espn.ros_build_metadata.items() if k != "espn_ownership"}
    right = {k: v for k, v in without_espn.ros_build_metadata.items() if k != "espn_ownership"}
    assert _canonical(left) == _canonical(right)
