"""Shared test fixtures.

`scripts/` is still imported by path because the Phase-0 probe is a script, not a package
module. Everything Phase 1 added is imported normally from the installed ``ffdraft``
package, so a test failing on import means the package is genuinely broken rather than a
path shim being wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"
PIPELINE_FIXTURES = FIXTURE_DIR / "pipeline"
SOURCE_SCHEMA_FIXTURES = FIXTURE_DIR / "source_schemas"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def pipeline_fixture_dir() -> Path:
    return PIPELINE_FIXTURES


@pytest.fixture(scope="session")
def app_config():
    from ffdraft.config import load_app_config

    # An explicit empty environment: no test may read a provisioned secret (ADR-017).
    return load_app_config(root=REPO_ROOT, environ={})


@pytest.fixture(scope="session")
def fixture_inputs():
    from ffdraft.pipeline import load_fixture_inputs

    return load_fixture_inputs(PIPELINE_FIXTURES)


@pytest.fixture(scope="session")
def pipeline_result(fixture_inputs, app_config):
    from ffdraft.pipeline import run_fixture_pipeline

    return run_fixture_pipeline(fixture_inputs, config=app_config, git_sha="0000000")


@pytest.fixture(scope="session")
def built_artifacts(tmp_path_factory, app_config) -> Path:
    """Run the full fixture pipeline once and hand every test the same output directory."""
    from ffdraft.pipeline import build_fixture_artifacts

    out_dir = tmp_path_factory.mktemp("artifacts")
    build_fixture_artifacts(
        fixture_dir=PIPELINE_FIXTURES,
        out_dir=out_dir,
        config=app_config,
        git_sha="0000000",
    )
    return out_dir


@pytest.fixture(scope="session")
def read_source_schema():
    """Return a loader for the Phase-0 recorded upstream schemas.

    Adapters are written against these, so tests read them here rather than restating the
    upstream column list - a restated list would drift from the evidence it stands in for.
    """

    def load(name: str) -> dict[str, Any]:
        path = SOURCE_SCHEMA_FIXTURES / f"{name}.schema.json"
        return json.loads(path.read_text(encoding="utf-8"))

    return load
