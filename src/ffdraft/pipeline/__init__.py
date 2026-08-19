"""Pipeline wiring.

Two pipelines live here. The Phase-1 fixture mini-pipeline proves the artifact contract
path end to end without a network. The Phase-2 historical build assembles the modelling
dataset from nflverse history; its pure core takes normalized frames, so the integration
tests drive it from fixtures too.
"""

from __future__ import annotations

from ffdraft.pipeline.fixture_pipeline import (
    FIXTURE_MODEL_VERSION,
    FixturePipelineResult,
    build_fixture_artifacts,
    load_fixture_inputs,
    run_fixture_pipeline,
)
from ffdraft.pipeline.historical import (
    DATASET_VERSION,
    DEFAULT_FIRST_SEASON,
    DEFAULT_HISTORICAL_DIR,
    HistoricalDataset,
    build_historical_dataset,
    default_target_seasons,
    load_historical_dataset,
    run_historical_build,
    write_historical_dataset,
)

__all__ = [
    "DATASET_VERSION",
    "DEFAULT_FIRST_SEASON",
    "DEFAULT_HISTORICAL_DIR",
    "FIXTURE_MODEL_VERSION",
    "FixturePipelineResult",
    "HistoricalDataset",
    "build_fixture_artifacts",
    "build_historical_dataset",
    "default_target_seasons",
    "load_fixture_inputs",
    "load_historical_dataset",
    "run_fixture_pipeline",
    "run_historical_build",
    "write_historical_dataset",
]
