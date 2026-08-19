"""Q1 — the simple direct-total LightGBM quantile candidate.

`docs/MODELING.md` section 9.1: for each position and scoring preset, predict the P10, P25,
P50, P75 and P90 of a player's season fantasy-point total. LightGBM's quantile objective
fits one booster per level, so a group is five boosters.

The configuration is fixed and conservative, and it is *predeclared*: Phase 3 asks whether a
simple nonlinear probabilistic model beats honest baselines out of time, not how high a
leaderboard score tuning can reach. No search of any kind runs here - no grid, no Optuna, no
early stopping against a validation season, no feature selection loop. Phase 4 owns
calibration and refinement.

Determinism is enforced rather than hoped for: a single thread, LightGBM's ``deterministic``
and ``force_row_wise`` modes, and every seed derived from the experiment seed plus the group
identity.

Missing values go to LightGBM as NaN and are handled natively, which is the whole reason the
nullable Phase-2 columns were never imputed upstream: ``years_exp`` missing means unknown
experience, not zero experience, and the tree learns a split for it.
"""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.estimators import FitContext, PredictionBlock, repair_monotonicity
from ffdraft.modeling.metrics import crossing_rate
from ffdraft.modeling.preprocessing import design_matrix

__all__ = ["Q1_PARAMETERS", "Q1_VERSION", "LightGbmQuantileCandidate"]

Floats = NDArray[np.float64]

Q1_VERSION = "q1_lgbm_quantile_v1"

#: Predeclared and fixed for the whole of Phase 3. Small trees, a low learning rate, a
#: generous leaf minimum and both kinds of subsampling, because the smallest group in the
#: shortest training window is only a few hundred rows.
Q1_PARAMETERS: dict[str, Any] = {
    "objective": "quantile",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 30,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "num_threads": 1,
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}

#: Fixed number of boosting rounds. There is no early stopping because the only data that
#: could stop it is the validation season, and looking at that would be the leak this whole
#: harness exists to prevent.
Q1_NUM_BOOST_ROUND = 250


class LightGbmQuantileCandidate:
    """Position-specific, scoring-specific, quantile-specific LightGBM."""

    model_id = "Q1"

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        num_boost_round: int = Q1_NUM_BOOST_ROUND,
    ) -> None:
        self.parameters = dict(parameters or Q1_PARAMETERS)
        self.num_boost_round = num_boost_round

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": Q1_VERSION,
            "family": "LightGBM quantile regression (direct season total)",
            "library": f"lightgbm {lgb.__version__}",
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "grain": "position x scoring preset x quantile",
            "tuning": "none; the configuration is fixed and predeclared for all of Phase 3",
            "missing_values": "passed to LightGBM as NaN and handled natively",
        }

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: FitContext,
    ) -> PredictionBlock:
        features = list(context.features)
        train_x = design_matrix(train, features)
        validate_x = design_matrix(validate, features)
        train_y = train.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()

        # Columns with no training values at all are dropped so the recorded feature count
        # reflects what the model could actually split on; LightGBM would ignore them anyway.
        usable = [
            index for index in range(train_x.shape[1]) if bool(np.any(~np.isnan(train_x[:, index])))
        ]
        used_names = [features[index] for index in usable]
        train_x = train_x[:, usable]
        validate_x = validate_x[:, usable]

        seed = context.group_seed
        columns: list[Floats] = []
        for level in context.levels:
            parameters = {
                **self.parameters,
                "alpha": level,
                "seed": seed,
                "data_random_seed": seed,
                "feature_fraction_seed": seed,
                "bagging_seed": seed,
                "extra_seed": seed,
            }
            dataset = lgb.Dataset(
                train_x,
                label=train_y,
                feature_name=used_names,
                free_raw_data=False,
            )
            booster = lgb.train(parameters, dataset, num_boost_round=self.num_boost_round)
            prediction = np.asarray(booster.predict(validate_x), dtype=np.float64)
            columns.append(prediction)

        raw = np.column_stack(columns) if columns else np.zeros((validate.height, 0))
        repaired = repair_monotonicity(raw)
        median_index = context.levels.index(0.50)
        return PredictionBlock(
            keys=validate,
            point=repaired[:, median_index].copy(),
            quantiles=repaired,
            raw_quantiles=raw,
            diagnostics={
                "seed": seed,
                "features_offered": len(features),
                "features_used": len(used_names),
                "train_rows": train.height,
                "validation_rows": validate.height,
                "crossing_rate_raw": crossing_rate(raw),
                "num_boost_round": self.num_boost_round,
            },
        )
