"""Pipeline wiring.

Phase 1 ships one pipeline: the network-free fixture mini-pipeline that proves the whole
contract path works end to end. Production pipelines arrive with the phases that own them.
"""

from __future__ import annotations

from ffdraft.pipeline.fixture_pipeline import (
    FIXTURE_MODEL_VERSION,
    FixturePipelineResult,
    build_fixture_artifacts,
    load_fixture_inputs,
    run_fixture_pipeline,
)

__all__ = [
    "FIXTURE_MODEL_VERSION",
    "FixturePipelineResult",
    "build_fixture_artifacts",
    "load_fixture_inputs",
    "run_fixture_pipeline",
]
