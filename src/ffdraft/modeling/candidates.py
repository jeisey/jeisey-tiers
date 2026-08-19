"""The intrinsic candidate models: Q1, the calibrated production form, and Candidate B.

Phase 3 built and froze **Q1**, described first below. Phase 4 adds two things beside it and
changes nothing about it, so `ffdraft evaluate-intrinsic` still reproduces the Phase-3
report exactly:

:class:`CalibratedQuantileCandidate`
    Q1's architecture and predeclared parameters wrapped in a calibration strategy and a
    target scale (`docs/MODELING.md` section 10, ADR-030). This is the production form of
    Candidate A.
:class:`AvailabilityPerformanceCandidate`
    **Candidate B**, the availability x performance hurdle from `docs/MODELING.md`
    section 9.2, which Phase 3 left unimplemented and unjudged.

## Q1 — the simple direct-total LightGBM quantile candidate

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

from collections.abc import Sequence
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.calibration import (
    CalibrationStrategy,
    IdentityTarget,
    MonotoneOnly,
    QuantileShift,
    TargetScale,
    monotone_projection,
    season_array,
)
from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.estimators import FitContext, PredictionBlock, repair_monotonicity
from ffdraft.modeling.gaussian import norm_cdf, norm_ppf
from ffdraft.modeling.metrics import crossing_rate
from ffdraft.modeling.preprocessing import design_matrix, inner_chronological_split
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.simulation.sampler import DomainBounds, QuantileFunction, normal_draws

__all__ = [
    "CANDIDATE_B_VERSION",
    "fit_quantile_boosters",
    "horizon_weeks_for",
    "predict_quantiles",
    "usable_columns",
    "HURDLE_COMPOSITION_DRAWS",
    "MAX_DEPENDENCE",
    "MINIMUM_DEPENDENCE_ROWS",
    "PRODUCTION_CANDIDATE_A_VERSION",
    "Q1_PARAMETERS",
    "Q1_VERSION",
    "AvailabilityPerformanceCandidate",
    "CalibratedQuantileCandidate",
    "LightGbmQuantileCandidate",
]

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

#: Candidate A in its production form. The architecture is Q1's; the version is separate
#: because the calibrated output is a different artifact with a different contract.
PRODUCTION_CANDIDATE_A_VERSION = "a1_lgbm_quantile_calibrated_v1"

CANDIDATE_B_VERSION = "cb_hurdle_availability_performance_v1"

#: Draws used to compose Candidate B's two components into a season-total distribution.
#: Enough to read five quantiles off an empirical sample without the sampling noise showing
#: up in the comparison; the production simulation's draw count is a separate decision
#: (``phase4_convergence_v1``) about a different quantity.
HURDLE_COMPOSITION_DRAWS = 2000

#: Fewer active player-seasons than this and the copula parameter is not estimated at all.
MINIMUM_DEPENDENCE_ROWS = 100

#: The copula correlation is clipped here. A |rho| of 1 would make the two components one
#: component, and an estimate that extreme from a few hundred rows is noise, not dependence.
MAX_DEPENDENCE = 0.95


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


# =======================================================================================
# Phase 4
# =======================================================================================


def fit_quantile_boosters(
    train_x: Floats,
    train_y: Floats,
    *,
    levels: Sequence[float],
    seed: int,
    feature_names: Sequence[str],
    parameters: dict[str, Any],
    num_boost_round: int,
) -> list[lgb.Booster]:
    """One booster per quantile level, all sharing the group's deterministic seed."""
    boosters: list[lgb.Booster] = []
    for level in levels:
        configured = {
            **parameters,
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
            feature_name=list(feature_names),
            free_raw_data=False,
        )
        boosters.append(lgb.train(configured, dataset, num_boost_round=num_boost_round))
    return boosters


def predict_quantiles(boosters: Sequence[lgb.Booster], matrix: Floats) -> Floats:
    columns = [np.asarray(booster.predict(matrix), dtype=np.float64) for booster in boosters]
    if not columns:
        return np.zeros((matrix.shape[0], 0), dtype=np.float64)
    return np.column_stack(columns)


def usable_columns(train_x: Floats, features: Sequence[str]) -> tuple[list[int], list[str]]:
    """Drop columns with no training values, so the recorded feature count is honest."""
    usable = [
        index for index in range(train_x.shape[1]) if bool(np.any(~np.isnan(train_x[:, index])))
    ]
    return usable, [features[index] for index in usable]


class CalibratedQuantileCandidate:
    """Candidate A for production: Q1 plus a declared calibration strategy and target scale.

    Q1 itself is untouched - :class:`LightGbmQuantileCandidate` still reproduces the Phase-3
    numbers exactly. This class wraps the same architecture and the same predeclared
    parameters with the two things Phase 4 adds:

    * a :class:`~ffdraft.modeling.calibration.CalibrationStrategy`, which owns the
      monotonicity repair and any fitted correction;
    * a :class:`~ffdraft.modeling.calibration.TargetScale`, which is the identity for the
      production model and the horizon normalization for the one predeclared sensitivity.

    When the strategy needs calibration data it is taken from an inner *chronological* split
    of the training window - the same construction :mod:`ffdraft.modeling.preprocessing`
    already uses to give the baselines honest residual quantiles. The model is then refitted
    on the whole training window, so calibration costs no training data; the recorded
    consequence is that the shifts describe a marginally weaker model than the one they are
    applied to, which biases intervals slightly wide rather than slightly narrow.
    """

    def __init__(
        self,
        model_id: str,
        *,
        calibration: CalibrationStrategy,
        target: TargetScale | None = None,
        parameters: dict[str, Any] | None = None,
        num_boost_round: int = Q1_NUM_BOOST_ROUND,
    ) -> None:
        self.model_id = model_id
        self.calibration = calibration
        self.target: TargetScale = target if target is not None else IdentityTarget()
        self.parameters = dict(parameters or Q1_PARAMETERS)
        self.num_boost_round = num_boost_round

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": PRODUCTION_CANDIDATE_A_VERSION,
            "family": "LightGBM quantile regression (direct season total), calibrated",
            "library": f"lightgbm {lgb.__version__}",
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "grain": "position x scoring preset x quantile",
            "tuning": "none; Q1's predeclared configuration is carried unchanged",
            "target_scale": self.target.describe(),
            "calibration": self.calibration.describe(),
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
        usable, used_names = usable_columns(train_x, features)
        train_x = train_x[:, usable]
        validate_x = design_matrix(validate, features)[:, usable]

        raw_target = train.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        train_y = self.target.forward(raw_target, season_array(train))
        seed = context.group_seed

        shift: QuantileShift | None = None
        inner: dict[str, Any] = {}
        if self.calibration.needs_calibration_split:
            split = inner_chronological_split(context.fold.train_seasons)
            fit_mask = pl.col("season").is_in(list(split.fit_seasons))
            inner_fit = train.filter(fit_mask)
            inner_calibration = train.filter(~fit_mask)
            if inner_fit.height and inner_calibration.height:
                inner_x = design_matrix(inner_fit, features)[:, usable]
                inner_y = self.target.forward(
                    inner_fit.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    season_array(inner_fit),
                )
                calibration_x = design_matrix(inner_calibration, features)[:, usable]
                calibration_y = self.target.forward(
                    inner_calibration.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    season_array(inner_calibration),
                )
                inner_boosters = fit_quantile_boosters(
                    inner_x,
                    inner_y,
                    levels=context.levels,
                    seed=seed,
                    feature_names=used_names,
                    parameters=self.parameters,
                    num_boost_round=self.num_boost_round,
                )
                shift = QuantileShift.fit(
                    calibration_y,
                    predict_quantiles(inner_boosters, calibration_x),
                    context.levels,
                )
            else:
                shift = QuantileShift.none(context.levels)
            inner = {**split.to_dict(), "shift": (shift.describe() if shift else None)}

        boosters = fit_quantile_boosters(
            train_x,
            train_y,
            levels=context.levels,
            seed=seed,
            feature_names=used_names,
            parameters=self.parameters,
            num_boost_round=self.num_boost_round,
        )
        raw_scaled = predict_quantiles(boosters, validate_x)
        calibrated_scaled = self.calibration.calibrate(raw_scaled, shift=shift)

        season = int(context.fold.validation_season)
        raw = self.target.inverse(raw_scaled, season)
        quantiles = self.target.inverse(calibrated_scaled, season)
        median_index = context.levels.index(0.50)
        return PredictionBlock(
            keys=validate,
            point=quantiles[:, median_index].copy(),
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={
                "seed": seed,
                "features_offered": len(features),
                "features_used": len(used_names),
                "train_rows": train.height,
                "validation_rows": validate.height,
                "crossing_rate_raw": crossing_rate(raw),
                "crossing_rate_post": crossing_rate(quantiles),
                "num_boost_round": self.num_boost_round,
                "target_scale": self.target.scale_id,
                "calibration_strategy": self.calibration.strategy_id,
                **inner,
            },
        )


class AvailabilityPerformanceCandidate:
    """Candidate B: a two-component hurdle model composed by Monte Carlo.

    `docs/MODELING.md` section 9.2 asks whether separating *how much a player plays* from
    *how well he plays when active* beats predicting the season total directly. The
    separation is real in this dataset: 44% of eligible player-seasons record zero games, so
    a direct model spends much of its capacity on an availability question dressed as a
    scoring question.

    Two components, both LightGBM quantile regressions on the same ``intrinsic_core_v1``
    features, both fitted inside the fold:

    ``availability``
        the share of the fantasy horizon a player is active for, ``games / horizon_weeks``.
        Modelling the *rate* rather than the count is what keeps 16-week and 17-week seasons
        comparable inside one training window; at prediction time it is multiplied back by
        the validation season's horizon and rounded to a whole number of games. This is
        internal to the candidate and changes no label contract.

    ``conditional performance``
        fantasy points per active game, fitted only on training rows that recorded at least
        one game, because points per game is undefined for the others.

    **Composition.** Season total is ``games x points-per-game``, and a player who draws zero
    games scores exactly zero. Nothing is clipped at zero from below: interceptions and lost
    fumbles make genuinely negative season totals possible, and 92 of them occur in the
    historical dataset.

    **Dependence.** The two components are *not* sampled independently. A Gaussian copula
    couples them through a single correlation estimated inside the fold, on the same inner
    chronological split the calibration uses: both components are fitted on the earlier
    seasons, each observation in the later seasons is mapped to its own predicted quantile
    function, and the correlation of the resulting normal scores is the parameter. It is
    estimated on players who actually played, because points per game is undefined for the
    others - a restriction worth stating, since it means the parameter describes the
    dependence among active players and is extrapolated to the rest.
    """

    model_id = "CB"

    def __init__(
        self,
        *,
        calibration: CalibrationStrategy | None = None,
        parameters: dict[str, Any] | None = None,
        num_boost_round: int = Q1_NUM_BOOST_ROUND,
        composition_draws: int = HURDLE_COMPOSITION_DRAWS,
        seed_material: Sequence[object] = ("candidate_b", "development"),
    ) -> None:
        self.calibration: CalibrationStrategy = calibration or MonotoneOnly()
        self.parameters = dict(parameters or Q1_PARAMETERS)
        self.num_boost_round = num_boost_round
        self.composition_draws = composition_draws
        self.seed_material = tuple(seed_material)

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": CANDIDATE_B_VERSION,
            "family": "availability x conditional performance hurdle, Monte Carlo composed",
            "library": f"lightgbm {lgb.__version__}",
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "components": {
                "availability": "LightGBM quantile regression on games / horizon weeks",
                "performance": (
                    "LightGBM quantile regression on fantasy points per active game, "
                    "fitted on training rows with at least one game"
                ),
            },
            "composition": {
                "draws": self.composition_draws,
                "rule": (
                    "round(rate x horizon weeks) games x points per game; zero games scores zero"
                ),
                "dependence": (
                    "Gaussian copula with one fold-fitted correlation, estimated from "
                    "probability-integral transforms on an inner chronological split"
                ),
                "negative_totals": "permitted; this project's scoring presets allow them",
            },
            "calibration": self.calibration.describe(),
            "grain": "position x scoring preset x quantile",
            "tuning": "none; Q1's predeclared LightGBM configuration is reused unchanged",
        }

    # -- component fitting --------------------------------------------------------------

    def _fit_components(
        self,
        frame: pl.DataFrame,
        matrix: Floats,
        *,
        levels: Sequence[float],
        seed: int,
        feature_names: Sequence[str],
    ) -> tuple[list[lgb.Booster], list[lgb.Booster], Floats, DomainBounds]:
        games = frame.get_column("actual_games_played").cast(pl.Float64).to_numpy()
        weeks = horizon_weeks_for(frame)
        rate = np.clip(games / weeks, 0.0, 1.0)
        availability = fit_quantile_boosters(
            matrix,
            rate,
            levels=levels,
            seed=seed,
            feature_names=feature_names,
            parameters=self.parameters,
            num_boost_round=self.num_boost_round,
        )
        played = games >= 1.0
        points = frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        per_game = np.divide(points, np.where(played, games, 1.0))
        performance = fit_quantile_boosters(
            matrix[played],
            per_game[played],
            levels=levels,
            seed=seed + 1,
            feature_names=feature_names,
            parameters=self.parameters,
            num_boost_round=self.num_boost_round,
        )
        return (
            availability,
            performance,
            per_game[played],
            DomainBounds.from_training(
                per_game[played],
            ),
        )

    def _quantile_functions(
        self,
        availability: Sequence[lgb.Booster],
        performance: Sequence[lgb.Booster],
        matrix: Floats,
        *,
        levels: Sequence[float],
        performance_bounds: DomainBounds,
    ) -> tuple[QuantileFunction, QuantileFunction]:
        rate = monotone_projection(predict_quantiles(availability, matrix))
        per_game = monotone_projection(predict_quantiles(performance, matrix))
        return (
            QuantileFunction(tuple(levels), rate, DomainBounds(0.0, 1.0)),
            QuantileFunction(tuple(levels), per_game, performance_bounds),
        )

    def _fit_dependence(
        self,
        frame: pl.DataFrame,
        rate_function: QuantileFunction,
        performance_function: QuantileFunction,
    ) -> tuple[float, int]:
        games = frame.get_column("actual_games_played").cast(pl.Float64).to_numpy()
        weeks = horizon_weeks_for(frame)
        played = games >= 1.0
        if int(np.count_nonzero(played)) < MINIMUM_DEPENDENCE_ROWS:
            return 0.0, int(np.count_nonzero(played))
        points = frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        per_game = np.divide(points, np.where(played, games, 1.0))
        u_rate = rate_function.probability_integral_transform(np.clip(games / weeks, 0.0, 1.0))
        u_performance = performance_function.probability_integral_transform(per_game)
        z_rate = norm_ppf(u_rate[played])
        z_performance = norm_ppf(u_performance[played])
        if float(np.std(z_rate)) < 1e-9 or float(np.std(z_performance)) < 1e-9:
            return 0.0, int(np.count_nonzero(played))
        correlation = float(np.corrcoef(z_rate, z_performance)[0, 1])
        if correlation != correlation:
            correlation = 0.0
        return float(np.clip(correlation, -MAX_DEPENDENCE, MAX_DEPENDENCE)), int(
            np.count_nonzero(played),
        )

    def _compose(
        self,
        validate: pl.DataFrame,
        rate_function: QuantileFunction,
        performance_function: QuantileFunction,
        *,
        correlation: float,
        levels: Sequence[float],
        season: int,
        context_key: str,
    ) -> Floats:
        weeks = float(fantasy_horizon(season).week_count)
        player_ids = validate.get_column("player_id").to_list()
        streams = normal_draws(
            player_ids,
            self.composition_draws,
            seed_material=(*self.seed_material, context_key, season),
            streams=2,
        )
        z_rate = streams[0]
        z_performance = correlation * z_rate + np.sqrt(1.0 - correlation**2) * streams[1]
        games = np.rint(rate_function.evaluate(norm_cdf(z_rate)) * weeks)
        games = np.clip(games, 0.0, weeks)
        per_game = performance_function.evaluate(norm_cdf(z_performance))
        totals = np.where(games > 0.0, games * per_game, 0.0)
        return np.quantile(totals, list(levels), axis=1).T.astype(np.float64)

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: FitContext,
    ) -> PredictionBlock:
        features = list(context.features)
        train_x = design_matrix(train, features)
        usable, used_names = usable_columns(train_x, features)
        train_x = train_x[:, usable]
        validate_x = design_matrix(validate, features)[:, usable]
        seed = context.group_seed
        context_key = f"{context.fold.fold_id}|{context.position}|{context.scoring_preset}"

        # The inner chronological split serves two purposes at once: the copula parameter
        # and, when the strategy asks for it, the calibration shifts. Both are estimated
        # from components fitted on strictly earlier seasons than the rows they are
        # measured on.
        split = inner_chronological_split(context.fold.train_seasons)
        fit_mask = pl.col("season").is_in(list(split.fit_seasons))
        inner_fit = train.filter(fit_mask)
        inner_calibration = train.filter(~fit_mask)
        correlation, dependence_rows = 0.0, 0
        shift: QuantileShift | None = None
        if inner_fit.height and inner_calibration.height:
            inner_x = design_matrix(inner_fit, features)[:, usable]
            calibration_x = design_matrix(inner_calibration, features)[:, usable]
            inner_availability, inner_performance, _, inner_bounds = self._fit_components(
                inner_fit,
                inner_x,
                levels=context.levels,
                seed=seed,
                feature_names=used_names,
            )
            inner_rate_function, inner_performance_function = self._quantile_functions(
                inner_availability,
                inner_performance,
                calibration_x,
                levels=context.levels,
                performance_bounds=inner_bounds,
            )
            correlation, dependence_rows = self._fit_dependence(
                inner_calibration,
                inner_rate_function,
                inner_performance_function,
            )
            if self.calibration.needs_calibration_split:
                composed = self._compose(
                    inner_calibration,
                    inner_rate_function,
                    inner_performance_function,
                    correlation=correlation,
                    levels=context.levels,
                    season=int(max(split.residual_seasons)),
                    context_key=f"{context_key}|inner",
                )
                shift = QuantileShift.fit(
                    inner_calibration.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    composed,
                    context.levels,
                )

        availability, performance, _, bounds = self._fit_components(
            train,
            train_x,
            levels=context.levels,
            seed=seed,
            feature_names=used_names,
        )
        rate_function, performance_function = self._quantile_functions(
            availability,
            performance,
            validate_x,
            levels=context.levels,
            performance_bounds=bounds,
        )
        raw = self._compose(
            validate,
            rate_function,
            performance_function,
            correlation=correlation,
            levels=context.levels,
            season=int(context.fold.validation_season),
            context_key=context_key,
        )
        quantiles = self.calibration.calibrate(raw, shift=shift)
        median_index = context.levels.index(0.50)
        return PredictionBlock(
            keys=validate,
            point=quantiles[:, median_index].copy(),
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={
                "seed": seed,
                "features_offered": len(features),
                "features_used": len(used_names),
                "train_rows": train.height,
                "validation_rows": validate.height,
                "crossing_rate_raw": crossing_rate(raw),
                "crossing_rate_post": crossing_rate(quantiles),
                "composition_draws": self.composition_draws,
                "dependence_correlation": correlation,
                "dependence_rows": dependence_rows,
                "performance_bounds": bounds.to_dict(),
                "calibration_strategy": self.calibration.strategy_id,
                **split.to_dict(),
                "shift": shift.describe() if shift else None,
            },
        )


def horizon_weeks_for(frame: pl.DataFrame) -> Floats:
    seasons = frame.get_column("season").to_list()
    lookup = {season: float(fantasy_horizon(int(season)).week_count) for season in set(seasons)}
    return np.array([lookup[season] for season in seasons], dtype=np.float64)
