"""Golden artifact comparison.

`docs/TEST_STRATEGY.md` section 4 endorses golden outputs for exactly this: artifact field
order and CSV headers, which a refactor changes silently. The comparison is structural
rather than byte-for-byte on purpose - a snapshot test that fails on every value change
teaches people to regenerate without reading the diff.

Regenerate with::

    uv run ffdraft build-fixture-artifacts --out tests/fixtures/artifacts --git-sha 0000000
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ffdraft.artifacts import ARTIFACT_SPECS, validate_artifact_directory

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "artifacts"
ENVELOPE_ARTIFACTS = sorted(ARTIFACT_SPECS)


@pytest.fixture(scope="module")
def golden() -> Path:
    assert GOLDEN_DIR.is_dir(), f"missing committed golden artifacts at {GOLDEN_DIR}"
    return GOLDEN_DIR


def test_committed_goldens_still_validate(golden):
    gate = validate_artifact_directory(golden)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


@pytest.mark.parametrize("artifact", ENVELOPE_ARTIFACTS)
def test_record_keys_match_a_fresh_build(artifact, golden, built_artifacts):
    spec = ARTIFACT_SPECS[artifact]
    committed = json.loads((golden / spec.json_filename).read_text())["records"]
    fresh = json.loads((built_artifacts / spec.json_filename).read_text())["records"]
    assert len(committed) == len(fresh)
    assert list(committed[0]) == list(fresh[0]), "record field order drifted"


@pytest.mark.parametrize(
    "artifact",
    [name for name in ENVELOPE_ARTIFACTS if ARTIFACT_SPECS[name].csv_filename],
)
def test_csv_headers_are_stable(artifact, golden, built_artifacts):
    filename = ARTIFACT_SPECS[artifact].csv_filename
    assert filename is not None

    def header(path: Path) -> list[str]:
        with (path / filename).open(encoding="utf-8", newline="") as handle:
            return next(csv.reader(handle))

    assert header(golden) == header(built_artifacts), f"{filename} header drifted"


def test_goldens_are_labelled_as_stub_output(golden):
    """A committed artifact must never be mistakable for production output."""
    metadata = json.loads((golden / "build_metadata.json").read_text())
    assert metadata["intrinsic_model_version"] == "fixture-stub-0"
    assert metadata["methodology_version"].startswith("phase1-fixture")
    assert metadata["git_sha"] == "0000000"
