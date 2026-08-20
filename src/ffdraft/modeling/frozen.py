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

from ffdraft.modeling.build_config import CurrentBuildConfig
from ffdraft.modeling.calibration import MonotoneOnly
from ffdraft.modeling.candidates import HURDLE_COMPOSITION_DRAWS
from ffdraft.modeling.folds import DEFAULT_SEED, WindowPolicy
from ffdraft.modeling.production import ARCHITECTURE_HURDLE, ProductionSpec
from ffdraft.modeling.rules import TIER_BOARD_DEPTH
from ffdraft.tiers.algorithms import ALTERNATIVE_ALGORITHM

__all__ = [
    "PRODUCTION_BUILD_CONFIG",
    "PRODUCTION_FINAL_HOLDOUT_SEASON",
    "PRODUCTION_FIRST_TRAINING_SEASON",
    "PRODUCTION_LAST_TRAINING_SEASON",
    "PRODUCTION_MODEL_ID",
    "PRODUCTION_SEASON",
    "PRODUCTION_SPEC",
    "PRODUCTION_WINDOW",
    "TIER_STABILITY_VERDICT",
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

#: The season sealed as the final holdout (ADR-025), named here so a build can assert that
#: the model it is about to serve was trained on it only after the holdout was evaluated.
PRODUCTION_FINAL_HOLDOUT_SEASON = 2025

#: The frozen tier stability gate's verdict on the configuration below, carried into every
#: build's metadata and the model card. Tiers ship having failed it: membership is
#: reproducible (bootstrap ARI 0.865) but boundaries are not sharply located (agreement
#: 0.239 against a 0.500 bar), and an artifact that did not say so would overstate them.
TIER_STABILITY_VERDICT = "fail"

#: The frozen simulation and tiering parameters, every one an outcome of a stage-C study.
#:
#: ``draws`` is the predeclared fallback rather than a converged count: no count in the
#: frozen ladder met every tolerance, and ADR-034 records why that is reported instead of
#: repaired. ``tier_algorithm`` is the documented alternative, reached because PELT failed
#: three clauses of the frozen stability gate (ADR-035), and ``tier_penalty`` is what
#: ``phase4_tier_v1`` selected for it - not the better-looking penalty the same grid offers.
PRODUCTION_BUILD_CONFIG = CurrentBuildConfig(
    draws=10000,
    ranking_statistic="median_vorp",
    tier_algorithm=ALTERNATIVE_ALGORITHM,
    tier_penalty=1.0,
    board_depth=TIER_BOARD_DEPTH,
    seed=DEFAULT_SEED,
    tier_stability_gate=TIER_STABILITY_VERDICT,
)
