"""Two bundles, two build ids — the shape production has and the fixture does not.

`daily-refresh` runs two builds. `build-current` writes the draft bundle under a
``2026-intrinsic-cb-hurdle-v1-…`` build id; `build-ros` writes the in-season bundle minutes
later under ``2026w01-intrinsic-ros-v1-…``. Both land in one directory, `validate-artifacts`
reads that directory once, and the rule it enforces is in `_IN_SEASON_ARTIFACTS`: **a build id
is compared inside a bundle and never across one.**

**The fixture build cannot express that.** It produces every artifact in one pass under one
build id, so a draft artifact and an in-season artifact trivially agree there, and an artifact
filed in the *wrong* bundle is invisible — its id matches whichever metadata it is compared
against. That is exactly what happened: ADR-089 published `behavior_trend_series` from the ROS
build and did not add it to `_IN_SEASON_ARTIFACTS`, every local gate passed, and the
2026-09-19 production refresh stopped at `validate-artifacts` with

    [critical] build_metadata.build_id_mismatch: behavior_trend_series carries a different
    build_id from build_metadata — observed: 2026w01-intrinsic-ros-v1-20260919T112638Z;
    expected: 2026-intrinsic-cb-hurdle-v1-20260919T112419Z

on a build whose numbers were all correct. The check was right; the membership list was wrong.

So this file builds the two-bundle shape from the committed goldens by **re-stamping the
in-season half with its own build id**, and asserts the three things that shape has to satisfy.
It is the ninth instance of the species `SESSION_STATE.md` records — a fixture that carried a
feature's shape and not its state — and the first one aimed at the *bundle boundary* rather
than at a rendering.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from ffdraft.artifacts import ARTIFACT_SPECS, validate_artifact_directory
from ffdraft.artifacts.validate import (
    _IN_SEASON_ARTIFACTS,
    ROS_BUILD_METADATA_FILENAME,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts"

#: What `build-ros` stamps on the in-season bundle, in production's own shape: a build id
#: that names the week, the ROS model and a later instant than the draft build's.
ROS_BUILD_ID = "2026w01-intrinsic-ros-v1-20260919T112638Z"


def ros_published_artifacts() -> set[str]:
    """The artifacts `run_ros_build` writes, read off the pipeline rather than restated.

    **This must not be `_IN_SEASON_ARTIFACTS`, and that is the whole point.** The first
    version of this file built its two-bundle fixture by iterating the membership list under
    test, so reverting the fix also stopped the fixture re-stamping the missing artifact, no
    mismatch occurred, and the test that exists to reproduce the production failure passed on
    the broken code. A fixture derived from the thing it is testing asserts its own
    assumptions.

    Deriving it from `ros.py` instead means the two disagree exactly when production would.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "ffdraft" / "pipeline" / "ros.py"
    ).read_text(encoding="utf-8")
    written = {
        name for name in ARTIFACT_SPECS if f'records["{name}"]' in source or f'"{name}": ' in source
    }
    assert written, "could not find the ROS build's published artifacts in pipeline/ros.py"
    return written


def _restamp(path: Path, build_id: str) -> None:
    """Rewrite one artifact's envelope and every record's ``build_id``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["build_id"] = build_id
    for record in payload.get("records", ()):
        if "build_id" in record:
            record["build_id"] = build_id
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


@pytest.fixture
def two_bundles(tmp_path: Path) -> Iterator[Path]:
    """The goldens, with the in-season half moved onto its own build id.

    Only the JSON envelopes are re-stamped. The CSVs are left alone deliberately: the CSV
    agreement check compares them with their JSON *records*, and `csv_flatten` does not carry
    `build_id` into a row, so a re-stamp that touched them would be testing the harness.
    """
    directory = tmp_path / "data"
    shutil.copytree(GOLDEN_DIR, directory)

    ros_metadata = directory / ROS_BUILD_METADATA_FILENAME
    payload = json.loads(ros_metadata.read_text(encoding="utf-8"))
    payload["build_id"] = ROS_BUILD_ID
    ros_metadata.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    for artifact in ros_published_artifacts():
        spec = ARTIFACT_SPECS[artifact]
        path = directory / spec.json_filename
        if path.is_file():
            _restamp(path, ROS_BUILD_ID)

    yield directory


def test_the_fixture_actually_produces_two_bundles(two_bundles: Path) -> None:
    """The premise, asserted rather than assumed.

    If a future change made the in-season half share the draft build id again, every
    assertion below would pass for the wrong reason — which is precisely how the original
    defect stayed invisible.
    """
    draft = json.loads((two_bundles / "build_metadata.json").read_text())["build_id"]
    ros = json.loads((two_bundles / ROS_BUILD_METADATA_FILENAME).read_text())["build_id"]
    assert draft != ros, "the two-bundle fixture collapsed back into one build id"
    assert ros == ROS_BUILD_ID


def test_two_bundles_with_two_build_ids_validate_cleanly(two_bundles: Path) -> None:
    """The production shape passes. This is the assertion the 2026-09-19 refresh failed."""
    gate = validate_artifact_directory(two_bundles)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


@pytest.mark.parametrize("artifact", sorted(ros_published_artifacts()))
def test_every_in_season_artifact_is_checked_against_the_ros_metadata(
    artifact: str,
    two_bundles: Path,
) -> None:
    """Membership is load-bearing in *both* directions, so both are asserted.

    Filing an artifact in the wrong bundle does two things, and the loud one hides the quiet
    one: the draft check fails on it, and the ROS check silently stops covering it. Breaking
    its id here must produce a `ros_build_metadata.build_id_mismatch` — if it produces
    nothing, this artifact has fallen out of `_IN_SEASON_ARTIFACTS` and is being checked by
    neither side.
    """
    spec = ARTIFACT_SPECS[artifact]
    path = two_bundles / spec.json_filename
    if not path.is_file():
        pytest.skip(f"{artifact} is not in the golden bundle")

    _restamp(path, "not-the-ros-build-id")
    gate = validate_artifact_directory(two_bundles)

    codes = {check.check_id for check in gate.critical_failures}
    assert "ros_build_metadata.build_id_mismatch" in codes, (
        f"{artifact} is published by the ROS build and no bundle checked its build id; "
        "it is missing from _IN_SEASON_ARTIFACTS"
    )
    assert "build_metadata.build_id_mismatch" not in codes, (
        f"{artifact} was compared against the DRAFT bundle's build id, which is the "
        "2026-09-19 failure reproduced"
    )


def test_a_draft_artifact_still_fails_against_the_draft_metadata(two_bundles: Path) -> None:
    """The other half of the rule, so the fix cannot become "stop comparing build ids".

    `tiers` belongs to the draft bundle. Re-stamping it with the ROS build id must fail —
    otherwise the membership list could be widened until nothing was checked at all.
    """
    _restamp(two_bundles / "tiers.json", ROS_BUILD_ID)
    gate = validate_artifact_directory(two_bundles)

    codes = {check.check_id for check in gate.critical_failures}
    assert "build_metadata.build_id_mismatch" in codes


def test_every_artifact_the_ros_build_writes_is_in_the_in_season_set() -> None:
    """The membership list against the pipeline that fills it.

    `_IN_SEASON_ARTIFACTS` is a hand-maintained set and the thing it has to agree with is
    `run_ros_build`'s `records` mapping. Reading the keys off the pipeline rather than
    restating them means a future in-season artifact fails *here*, on a unit test, instead of
    in production three minutes into a refresh.
    """
    missing = ros_published_artifacts() - _IN_SEASON_ARTIFACTS
    assert not missing, (
        f"{sorted(missing)} is written by the ROS build and missing from "
        "_IN_SEASON_ARTIFACTS, so validate-artifacts will compare it against the DRAFT "
        "bundle's build id and fail a correct production build"
    )
