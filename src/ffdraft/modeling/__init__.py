"""Phase-3 intrinsic baselines, candidates and the evaluation harness.

The subsystem boundary is deliberate: this package knows how to *evaluate* a model on the
Phase-2 historical dataset. It does not fetch anything, does not write public artifacts and
does not know what a tier is.

Read the modules in this order:

``holdout``
    The sealed final holdout and the authorization needed to open it.
``folds``
    Chronological rolling-origin folds and the two training-window policies.
``features``
    The versioned Phase-3 core model-feature set and its era-stability audit.
``dataset``
    Features joined to labels, with the sealed seasons already removed.
``preprocessing``
    Fold-local imputation, standardization and residual quantiles.
``estimators``
    The one interface every baseline and candidate implements.
``baselines`` / ``candidates``
    B0, B1 and Q1.
``metrics`` / ``bootstrap``
    Point, rank and probabilistic metrics, and paired uncertainty.
``gate``
    The promotion criteria and the window-selection rule, frozen before the comparison.
``experiment`` / ``report``
    Orchestration and serialization.
"""

from __future__ import annotations

from ffdraft.modeling.baselines import NaivePriorProductionBaseline, RidgeBaseline
from ffdraft.modeling.bootstrap import PairedCell, paired_bootstrap
from ffdraft.modeling.candidates import LightGbmQuantileCandidate
from ffdraft.modeling.dataset import ModelingDataset, load_modeling_dataset
from ffdraft.modeling.experiment import (
    EXPERIMENT_VERSION,
    ExperimentConfig,
    ExperimentResult,
    experiment_checks,
    run_experiment,
)
from ffdraft.modeling.features import CORE_FEATURE_SET_VERSION, core_feature_selection
from ffdraft.modeling.folds import (
    DEFAULT_SEED,
    DEVELOPMENT_VALIDATION_SEASONS,
    Fold,
    WindowPolicy,
    development_folds,
)
from ffdraft.modeling.gate import PROMOTION_CRITERIA, evaluate_promotion_gate
from ffdraft.modeling.holdout import (
    FINAL_HOLDOUT_SEASON,
    FinalEvalAuthorization,
    HoldoutSealError,
)
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.modeling.report import write_report

__all__ = [
    "CORE_FEATURE_SET_VERSION",
    "DEFAULT_SEED",
    "DEVELOPMENT_VALIDATION_SEASONS",
    "EXPERIMENT_VERSION",
    "FINAL_HOLDOUT_SEASON",
    "PROMOTION_CRITERIA",
    "QUANTILE_LEVELS",
    "ExperimentConfig",
    "ExperimentResult",
    "FinalEvalAuthorization",
    "Fold",
    "HoldoutSealError",
    "LightGbmQuantileCandidate",
    "ModelingDataset",
    "NaivePriorProductionBaseline",
    "PairedCell",
    "RidgeBaseline",
    "WindowPolicy",
    "core_feature_selection",
    "development_folds",
    "evaluate_promotion_gate",
    "experiment_checks",
    "load_modeling_dataset",
    "paired_bootstrap",
    "run_experiment",
    "write_report",
]
