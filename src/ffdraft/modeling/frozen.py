"""The Phase-4 freeze checkpoint: the production system, in one place, in code.

Everything a production build needs to be reproducible is a constant here, and every
constant is the *outcome of a decision a frozen rule made*, recorded with the study that
produced it. Nothing in this module may change in response to the final holdout: it is
written and committed before 2025 is opened, and the commit that contains it is the evidence
that the design was fixed first.

Reading order for anyone auditing a build:

* `docs/experiments/phase4-intrinsic-distribution/` — the architecture, calibration and
  target-scale decisions (ADR-031, ADR-032, ADR-033);
* `docs/experiments/phase4-simulation-ranking/` — the Monte Carlo draw count and the
  fair-ranking statistic (ADR-034);
* `docs/experiments/phase4-tier-segmentation/` — the tier penalty and its stability
  (ADR-035);
* `docs/experiments/phase4-final-holdout/` — the single 2025 evaluation, run last.
"""

from __future__ import annotations

from ffdraft.modeling.calibration import MonotoneOnly
from ffdraft.modeling.candidates import HURDLE_COMPOSITION_DRAWS
from ffdraft.modeling.folds import DEFAULT_SEED, WindowPolicy
from ffdraft.modeling.production import ARCHITECTURE_HURDLE, ProductionSpec
from ffdraft.modeling.rules import TIER_BOARD_DEPTH
from ffdraft.pipeline.current import CurrentBuildConfig

__all__ = [
    "PRODUCTION_BUILD_CONFIG",
    "PRODUCTION_FIRST_TRAINING_SEASON",
    "PRODUCTION_LAST_TRAINING_SEASON",
    "PRODUCTION_MODEL_ID",
    "PRODUCTION_SEASON",
    "PRODUCTION_SPEC",
    "PRODUCTION_WINDOW",
]

#: The model id the evaluation harness knows the promoted architecture by (ADR-033).
PRODUCTION_MODEL_ID = "CB"

#: The training window (ADR-028), unchanged by Phase 4.
PRODUCTION_WINDOW = WindowPolicy.W1
PRODUCTION_FIRST_TRAINING_SEASON = 2014

#: The last season the production model may train on. 2025 is the sealed final holdout
#: (ADR-025); it enters the training window only after that holdout has been evaluated once.
PRODUCTION_LAST_TRAINING_SEASON = 2025

#: The season the current build produces a board for.
PRODUCTION_SEASON = 2026

#: The frozen architecture. Every field is a decision, not a default.
PRODUCTION_SPEC = ProductionSpec(
    model_version="intrinsic-cb-hurdle-v1",
    architecture=ARCHITECTURE_HURDLE,
    calibration_strategy_id=MonotoneOnly().strategy_id,
    target_scale_id="season_total",
    seed=DEFAULT_SEED,
    composition_draws=HURDLE_COMPOSITION_DRAWS,
)

#: The frozen simulation and tiering parameters. Filled from the stage-C studies.
PRODUCTION_BUILD_CONFIG = CurrentBuildConfig(
    draws=10000,
    ranking_statistic="median_vorp",
    tier_penalty=5.0,
    board_depth=TIER_BOARD_DEPTH,
    seed=DEFAULT_SEED,
)
