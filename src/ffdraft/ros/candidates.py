"""The rest-of-season candidate: `RC1`, an availability x performance hurdle.

`docs/RELEASE2_ROADMAP.md` 11.2 asks Phase 11 to model remaining availability, conditional
performance and their composition, and says of Release 1's hurdle: *"Preserve the successful
V1 hurdle concept if validation supports it; do not assume it must win simply because it won
preseason."* RC1 is that concept at the rest-of-season grain, and it is the **only**
candidate. Building a second architecture before the first has cleared the declared
baselines would be optimizing for interest rather than for evidence, and the phase brief asks
for the smallest model that passes the declared gates.

The separation is even more clearly right here than it was preseason: **53.7% of modelled
snapshot rows have zero remaining games**, because a rest-of-season universe is full of
players who will not appear again. A direct model of remaining points would spend most of its
capacity on an availability question dressed up as a scoring question.

Two components, both LightGBM quantile regressions on the same ``ros_core_v1`` features:

``availability``
    ``actual_remaining_games / remaining_horizon_weeks``. A rate, not a count, because the
    remaining horizon shrinks from sixteen weeks to one across the season and the two ends
    have to be comparable inside one training window. At prediction time it is multiplied
    back by the row's own remaining horizon and rounded to whole games.

``conditional performance``
    fantasy points per remaining appearance, fitted only on training rows that record at
    least one remaining game, because points per game is undefined for the others.

**Composition and dependence** are Release 1's: a Gaussian copula with one correlation
estimated inside the fold on an inner chronological split, then a Monte Carlo composition of
``games x points-per-game`` where zero games scores exactly zero. Nothing is clipped at zero
from below; interceptions and lost fumbles make genuinely negative remaining totals possible.

**Nothing is tuned.** Q1's predeclared LightGBM configuration is reused unchanged, there is
no grid, no early stopping and no feature selection loop. The one parameter that differs is
the thread count, and it is a determinism-preserving speed setting rather than a modelling
choice: LightGBM's ``deterministic`` and ``force_row_wise`` modes make a multi-threaded fit
bit-identical to a single-threaded one, which a test asserts rather than assumes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.calibration import monotone_projection
from ffdraft.modeling.candidates import (
    HURDLE_COMPOSITION_DRAWS,
    MAX_DEPENDENCE,
    MINIMUM_DEPENDENCE_ROWS,
    Q1_PARAMETERS,
    fit_quantile_boosters,
    predict_quantiles,
    usable_columns,
)
from ffdraft.modeling.estimators import PredictionBlock, repair_monotonicity
from ffdraft.modeling.gaussian import norm_cdf, norm_ppf
from ffdraft.modeling.metrics import crossing_rate
from ffdraft.modeling.preprocessing import design_matrix, inner_chronological_split
from ffdraft.ros.estimators import ROS_TARGET_COLUMN, RosFitContext
from ffdraft.simulation.sampler import DomainBounds, QuantileFunction, normal_draws

__all__ = [
    "RC1_NUM_BOOST_ROUND",
    "RC1_PARAMETERS",
    "RC1_VERSION",
    "FittedComponents",
    "RosHurdleCandidate",
]

Floats = NDArray[np.float64]

RC1_VERSION = "rc1_ros_hurdle_v1"

#: Q1's predeclared configuration, unchanged except for the thread count. Small trees, a low
#: learning rate, a generous leaf minimum and both kinds of subsampling.
RC1_PARAMETERS: dict[str, Any] = {**Q1_PARAMETERS, "num_threads": 4}

#: Fixed rounds. There is no early stopping because the only data that could stop it is the
#: validation season, and looking at that would be the leak this harness exists to prevent.
RC1_NUM_BOOST_ROUND = 250

_REMAINING_GAMES = "actual_remaining_games"
_REMAINING_WEEKS = "remaining_horizon_weeks"


def remaining_weeks_of(frame: pl.DataFrame) -> Floats:
    """Each row's own remaining horizon, in weeks. Varies within a season by construction."""
    return frame.get_column(_REMAINING_WEEKS).cast(pl.Float64).to_numpy().astype(np.float64)


def _row_keys(frame: pl.DataFrame) -> list[str]:
    """Per-row Monte Carlo stream keys.

    A player appears at every cutoff of his season, so keying the draws on ``player_id``
    alone would give week 4 and week 5 the same uniforms and make their Monte Carlo error
    perfectly correlated. The cutoff is part of the key for that reason.
    """
    return [
        f"{player}|{week:02d}"
        for player, week in zip(
            frame.get_column("player_id").to_list(),
            frame.get_column("through_week").to_list(),
            strict=True,
        )
    ]


def _inner_seed(fitted: FittedComponents) -> int:
    """The seed the inner dependence fit uses.

    Derived from the outer fit's feature list and row count rather than passed in, so a
    production fit cannot vary it and two fits of the same window agree exactly.
    """
    material = f"{len(fitted.features)}|{fitted.train_rows}|{len(fitted.levels)}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647


@dataclass(frozen=True)
class FittedComponents:
    """One fitted hurdle: both component ladders plus what they were fitted on.

    Returned by :meth:`RosHurdleCandidate.fit_components` so the attribution diagnostics can
    explain exactly the boosters a prediction came from rather than refitting their own.
    """

    availability: tuple[lgb.Booster, ...]
    performance: tuple[lgb.Booster, ...]
    bounds: DomainBounds
    features: tuple[str, ...]
    usable: tuple[int, ...]
    levels: tuple[float, ...]
    train_rows: int

    def design(self, frame: pl.DataFrame) -> Floats:
        """The design matrix for ``frame``, restricted to the columns the fit actually used."""
        return design_matrix(frame, list(self.features))

    def describe(self) -> dict[str, Any]:
        return {
            "features_used": list(self.features),
            "levels": list(self.levels),
            "train_rows": self.train_rows,
            "performance_bounds": self.bounds.to_dict(),
        }


class RosHurdleCandidate:
    """RC1: remaining availability x conditional remaining performance, Monte Carlo composed."""

    model_id = "RC1"

    def __init__(
        self,
        *,
        parameters: dict[str, Any] | None = None,
        num_boost_round: int = RC1_NUM_BOOST_ROUND,
        composition_draws: int = HURDLE_COMPOSITION_DRAWS,
        seed_material: Sequence[object] = ("ros_candidate", "development"),
    ) -> None:
        self.parameters = dict(parameters or RC1_PARAMETERS)
        self.num_boost_round = num_boost_round
        self.composition_draws = composition_draws
        self.seed_material = tuple(seed_material)

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": RC1_VERSION,
            "family": (
                "remaining availability x conditional remaining performance hurdle, "
                "Monte Carlo composed"
            ),
            "library": f"lightgbm {lgb.__version__}",
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "components": {
                "availability": (
                    "LightGBM quantile regression on remaining games / remaining horizon weeks"
                ),
                "performance": (
                    "LightGBM quantile regression on fantasy points per remaining appearance, "
                    "fitted on training rows with at least one remaining game"
                ),
            },
            "composition": {
                "draws": self.composition_draws,
                "rule": (
                    "round(rate x this row's remaining horizon weeks) games x points per "
                    "game; zero games scores zero"
                ),
                "dependence": (
                    "Gaussian copula with one fold-fitted correlation, estimated from "
                    "probability-integral transforms on an inner chronological split"
                ),
                "stream_key": "player_id and through_week",
                "negative_totals": "permitted; this project's scoring presets allow them",
            },
            "calibration": "monotone projection only; no fitted shift",
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
    ) -> tuple[list[lgb.Booster], list[lgb.Booster], DomainBounds]:
        games = frame.get_column(_REMAINING_GAMES).cast(pl.Float64).to_numpy()
        weeks = remaining_weeks_of(frame)
        rate = np.clip(np.divide(games, np.where(weeks > 0.0, weeks, 1.0)), 0.0, 1.0)
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
        points = frame.get_column(ROS_TARGET_COLUMN).cast(pl.Float64).to_numpy()
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
        return availability, performance, DomainBounds.from_training(per_game[played])

    @staticmethod
    def _quantile_functions(
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

    @staticmethod
    def _fit_dependence(
        frame: pl.DataFrame,
        rate_function: QuantileFunction,
        performance_function: QuantileFunction,
    ) -> tuple[float, int]:
        games = frame.get_column(_REMAINING_GAMES).cast(pl.Float64).to_numpy()
        weeks = remaining_weeks_of(frame)
        played = games >= 1.0
        if int(np.count_nonzero(played)) < MINIMUM_DEPENDENCE_ROWS:
            return 0.0, int(np.count_nonzero(played))
        points = frame.get_column(ROS_TARGET_COLUMN).cast(pl.Float64).to_numpy()
        per_game = np.divide(points, np.where(played, games, 1.0))
        rate = np.clip(np.divide(games, np.where(weeks > 0.0, weeks, 1.0)), 0.0, 1.0)
        u_rate = rate_function.probability_integral_transform(rate)
        u_performance = performance_function.probability_integral_transform(per_game)
        z_rate = norm_ppf(u_rate[played])
        z_performance = norm_ppf(u_performance[played])
        if float(np.std(z_rate)) < 1e-9 or float(np.std(z_performance)) < 1e-9:
            return 0.0, int(np.count_nonzero(played))
        correlation = float(np.corrcoef(z_rate, z_performance)[0, 1])
        if correlation != correlation:
            correlation = 0.0
        return (
            float(np.clip(correlation, -MAX_DEPENDENCE, MAX_DEPENDENCE)),
            int(np.count_nonzero(played)),
        )

    def compose_draws(
        self,
        frame: pl.DataFrame,
        rate_function: QuantileFunction,
        performance_function: QuantileFunction,
        *,
        correlation: float,
        context_key: str,
    ) -> tuple[Floats, Floats]:
        """The composed Monte Carlo draws themselves: ``(games, totals)``.

        Split out of :meth:`_compose` so a production build can publish the *games* half of
        the hurdle - "how many appearances are left" is a quantity a reader of the board
        asks for directly - without a second draw loop that could disagree with the first.
        The arithmetic is unchanged; :meth:`_compose` is now this function plus a quantile.
        """
        weeks = remaining_weeks_of(frame)[:, None]
        streams = normal_draws(
            _row_keys(frame),
            self.composition_draws,
            seed_material=(*self.seed_material, context_key),
            streams=2,
        )
        z_rate = streams[0]
        z_performance = correlation * z_rate + np.sqrt(1.0 - correlation**2) * streams[1]
        games = np.clip(np.rint(rate_function.evaluate(norm_cdf(z_rate)) * weeks), 0.0, weeks)
        per_game = performance_function.evaluate(norm_cdf(z_performance))
        totals = np.where(games > 0.0, games * per_game, 0.0)
        return games, totals

    def _compose(
        self,
        frame: pl.DataFrame,
        rate_function: QuantileFunction,
        performance_function: QuantileFunction,
        *,
        correlation: float,
        levels: Sequence[float],
        context_key: str,
    ) -> Floats:
        _, totals = self.compose_draws(
            frame,
            rate_function,
            performance_function,
            correlation=correlation,
            context_key=context_key,
        )
        return np.quantile(totals, list(levels), axis=1).T.astype(np.float64)

    # -- reuse hooks for the production fit ---------------------------------------------
    #
    # ADR-078's claim that a production refit runs "the same code path" is only true if the
    # production fitter calls these rather than reimplementing them. They are thin public
    # names for the three steps :meth:`fit_predict` already performs, and they add no
    # behaviour of their own.

    quantile_functions = _quantile_functions

    def fit_production_dependence(
        self,
        train: pl.DataFrame,
        fitted: FittedComponents,
    ) -> tuple[float, int]:
        """The copula correlation for a production fit, estimated exactly as a fold's is.

        The same inner chronological split :meth:`fit_predict` uses: components are refitted
        on the earlier seasons of the training window and the correlation is measured on the
        later ones, so the dependence is never estimated on the rows that fitted it.
        """
        seasons = sorted({int(value) for value in train.get_column("season").to_list()})
        split = inner_chronological_split(seasons)
        fit_mask = pl.col("season").is_in(list(split.fit_seasons))
        inner_fit = train.filter(fit_mask)
        inner_dependence = train.filter(~fit_mask)
        if inner_fit.is_empty() or inner_dependence.is_empty():
            return 0.0, 0
        features = list(fitted.features)
        inner_x = design_matrix(inner_fit, features)
        dependence_x = design_matrix(inner_dependence, features)
        availability, performance, bounds = self._fit_components(
            inner_fit,
            inner_x,
            levels=fitted.levels,
            seed=_inner_seed(fitted),
            feature_names=features,
        )
        rate_function, performance_function = self._quantile_functions(
            availability,
            performance,
            dependence_x,
            levels=fitted.levels,
            performance_bounds=bounds,
        )
        return self._fit_dependence(inner_dependence, rate_function, performance_function)

    def fit_components(
        self,
        train: pl.DataFrame,
        context: RosFitContext,
    ) -> FittedComponents:
        """Fit both component ladders on ``train`` and return them.

        :meth:`fit_predict` uses this, and so does :mod:`ffdraft.ros.attribution`; there is
        one fitting path, so an explanation can never describe a model the predictions did
        not come from.
        """
        features = list(context.features)
        train_x = design_matrix(train, features)
        usable, used_names = usable_columns(train_x, features)
        availability, performance, bounds = self._fit_components(
            train,
            train_x[:, usable],
            levels=context.levels,
            seed=context.group_seed,
            feature_names=used_names,
        )
        return FittedComponents(
            availability=tuple(availability),
            performance=tuple(performance),
            bounds=bounds,
            features=tuple(used_names),
            usable=tuple(usable),
            levels=tuple(context.levels),
            train_rows=train.height,
        )

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        features = list(context.features)
        train_x = design_matrix(train, features)
        usable, used_names = usable_columns(train_x, features)
        train_x = train_x[:, usable]
        validate_x = design_matrix(validate, features)[:, usable]
        seed = context.group_seed
        context_key = f"{context.fold.fold_id}|{context.position}|{context.scoring_preset}"

        split = inner_chronological_split(context.fold.train_seasons)
        fit_mask = pl.col("season").is_in(list(split.fit_seasons))
        inner_fit = train.filter(fit_mask)
        inner_dependence = train.filter(~fit_mask)
        correlation, dependence_rows = 0.0, 0
        if inner_fit.height and inner_dependence.height:
            inner_x = design_matrix(inner_fit, features)[:, usable]
            dependence_x = design_matrix(inner_dependence, features)[:, usable]
            inner_availability, inner_performance, inner_bounds = self._fit_components(
                inner_fit,
                inner_x,
                levels=context.levels,
                seed=seed,
                feature_names=used_names,
            )
            inner_rate, inner_per_game = self._quantile_functions(
                inner_availability,
                inner_performance,
                dependence_x,
                levels=context.levels,
                performance_bounds=inner_bounds,
            )
            correlation, dependence_rows = self._fit_dependence(
                inner_dependence,
                inner_rate,
                inner_per_game,
            )

        availability, performance, bounds = self._fit_components(
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
            context_key=context_key,
        )
        quantiles = repair_monotonicity(raw)
        median_index = list(context.levels).index(0.50)
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
                **split.to_dict(),
            },
        )
