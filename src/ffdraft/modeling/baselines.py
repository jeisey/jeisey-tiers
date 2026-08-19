"""The two Phase-3 baselines a candidate has to beat.

``B0`` — naive prior production
    Prior-season points per game in the row's own scoring flavour, times the games a player
    with that availability history and age typically goes on to play. Players without usable
    prior production - rookies, and veterans whose previous season produced no qualifying
    stat line - get a draft-capital prior instead. Every number in it is a training-fold
    statistic, and any single prediction can be explained in one sentence: *this much per
    game, times the games a player like this usually plays*.

    It is deliberately a **strong** naive baseline rather than a convenient one. The obvious
    alternative - last season's point total - is beaten by it on every development season
    tried, because last season's games played is an availability signal in its own right and
    conditioning the expected-games multiplier on it uses that signal honestly. A baseline
    chosen to be easy to beat would make the promotion gate meaningless.

``B1`` — simple regularized point model
    Ridge regression on the Phase-3 core feature set, with imputation, missingness
    indicators and standardization all learned inside the fold. Its purpose is not to win;
    it is to answer whether a nonlinear boosted model is buying anything over an ordinary
    regularized linear one.

Both emit the same five quantiles as the candidate, from training-fold residuals collected
on an inner chronological split (:mod:`ffdraft.modeling.preprocessing`). Giving a baseline a
fabricated fixed-width interval would make the probabilistic comparison meaningless, and
giving it none at all would make it uncomparable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.estimators import FitContext, PredictionBlock, repair_monotonicity
from ffdraft.modeling.preprocessing import (
    FoldPreprocessor,
    ResidualQuantiles,
    design_matrix,
    inner_chronological_split,
    scalar_float,
)

__all__ = ["B0_VERSION", "B1_VERSION", "NaivePriorProductionBaseline", "RidgeBaseline"]

Floats = NDArray[np.float64]

B0_VERSION = "b0_prior_production_v1"
B1_VERSION = "b1_ridge_v1"

#: Candidate shrinkage weights for B0, in games: a player with exactly this many prior-season
#: games is pulled halfway towards the position's typical rate. The grid is tiny and
#: predeclared, and the value is chosen on an inner chronological split of the *training*
#: window - never against the validation season. Zero is included because regression to the
#: mean is already carried by the expected-games multiplier, and a fold where the extra
#: shrinkage does not help should be free to decline it.
B0_SHRINKAGE_GRID: tuple[float, ...] = (0.0, 2.0, 4.0, 8.0)

#: A training-fold bucket smaller than this falls back to the next coarser statistic rather
#: than trusting a mean of a handful of rows.
MINIMUM_BUCKET_ROWS = 20

#: The predeclared ridge penalty grid. Five values, chosen by an inner chronological split
#: of the training window - never by validation-season performance.
RIDGE_ALPHAS: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0)


def _age_bucket(frame: pl.DataFrame) -> pl.Series:
    """Coarse age cohorts. Wide enough that every bucket has training rows in every fold."""
    return frame.select(
        pl.when(pl.col("age_at_anchor").is_null())
        .then(pl.lit("unknown"))
        .when(pl.col("age_at_anchor") < 24.0)
        .then(pl.lit("under_24"))
        .when(pl.col("age_at_anchor") < 27.0)
        .then(pl.lit("24_26"))
        .when(pl.col("age_at_anchor") < 30.0)
        .then(pl.lit("27_29"))
        .otherwise(pl.lit("30_plus"))
        .alias("age_bucket"),
    ).get_column("age_bucket")


def _games_bucket(frame: pl.DataFrame) -> pl.Series:
    """Previous-season availability cohorts.

    Games played last season is the single most useful availability signal the naive
    baseline has: a player who finished a full season is far likelier to play a full one
    again than one who managed four. Conditioning the expected-games multiplier on it is
    what makes B0 competitive with - and better than - a raw prior-season total.
    """
    return frame.select(
        pl.when(pl.col("prev1_games").is_null())
        .then(pl.lit("none"))
        .when(pl.col("prev1_games") <= 4)
        .then(pl.lit("g0_4"))
        .when(pl.col("prev1_games") <= 8)
        .then(pl.lit("g5_8"))
        .when(pl.col("prev1_games") <= 12)
        .then(pl.lit("g9_12"))
        .when(pl.col("prev1_games") <= 14)
        .then(pl.lit("g13_14"))
        .otherwise(pl.lit("g15_plus"))
        .alias("games_bucket"),
    ).get_column("games_bucket")


def _draft_bucket(frame: pl.DataFrame) -> pl.Series:
    return frame.select(
        pl.when(~pl.col("drafted_flag"))
        .then(pl.lit("undrafted"))
        .when(pl.col("draft_round") <= 1)
        .then(pl.lit("round_1"))
        .when(pl.col("draft_round") <= 3)
        .then(pl.lit("round_2_3"))
        .otherwise(pl.lit("round_4_7"))
        .alias("draft_bucket"),
    ).get_column("draft_bucket")


def _has_prior_production(frame: pl.DataFrame) -> pl.Series:
    """Usable prior production: a matched prior points-per-game and the games behind it."""
    return frame.select(
        (
            pl.col("prior_ppg_matched").is_not_null()
            & pl.col("prev1_games").is_not_null()
            & (pl.col("prev1_games") > 0)
        ).alias("has_prior_production"),
    ).get_column("has_prior_production")


@dataclass
class _B0Fit:
    """Every statistic B0 learned, all of it from training rows."""

    shrinkage_games: float
    position_rate: float
    expected_games_pair: dict[tuple[str, str], float]
    expected_games_by_availability: dict[str, float]
    default_games: float
    no_prior_prior: dict[str, float]
    default_no_prior: float

    def describe(self) -> dict[str, Any]:
        return {
            "shrinkage_games": self.shrinkage_games,
            "position_typical_rate": round(self.position_rate, 4),
            "expected_games_by_availability_and_age": {
                f"{games}|{age}": round(value, 3)
                for (games, age), value in sorted(self.expected_games_pair.items())
            },
            "expected_games_by_availability": {
                bucket: round(value, 3)
                for bucket, value in sorted(self.expected_games_by_availability.items())
            },
            "default_expected_games": round(self.default_games, 3),
            "no_prior_production_prior_by_draft_bucket": {
                bucket: round(value, 3) for bucket, value in sorted(self.no_prior_prior.items())
            },
            "default_no_prior_production_prior": round(self.default_no_prior, 3),
        }


class NaivePriorProductionBaseline:
    """B0. Transparent, training-fold-only, and the model every candidate must beat."""

    model_id = "B0"

    def __init__(self, shrinkage_grid: Sequence[float] = B0_SHRINKAGE_GRID) -> None:
        self.shrinkage_grid = tuple(shrinkage_grid)

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": B0_VERSION,
            "family": "naive prior production",
            "point_rule": (
                "veterans: prior-season points per game in the row's scoring flavour, "
                "optionally shrunk towards the position's typical rate, times the "
                "training-fold mean games played by players in the same previous-season "
                "availability and age cohort; players without usable prior production: the "
                "training-fold mean season total for their draft-capital bucket"
            ),
            "shrinkage_grid": list(self.shrinkage_grid),
            "shrinkage_selection": (
                "lowest MAE on an inner chronological split of the training window; the "
                "validation season is never consulted"
            ),
            "availability_buckets": ["none", "g0_4", "g5_8", "g9_12", "g13_14", "g15_plus"],
            "age_buckets": ["unknown", "under_24", "24_26", "27_29", "30_plus"],
            "minimum_bucket_rows": MINIMUM_BUCKET_ROWS,
            "quantiles": "training-fold residuals from an inner chronological split",
            "fitted_statistics": "training fold only",
        }

    def _fit(self, train: pl.DataFrame, shrinkage: float) -> _B0Fit:
        has_prior = _has_prior_production(train)
        veterans = train.filter(has_prior)
        others = train.filter(~has_prior)

        rates = veterans.get_column("prior_ppg_matched").drop_nulls()
        position_rate = scalar_float(rates.median()) if rates.len() else 0.0

        pair: dict[tuple[str, str], float] = {}
        single: dict[str, float] = {}
        default_games = 0.0
        if veterans.height:
            annotated = veterans.with_columns(
                _games_bucket(veterans).alias("games_bucket"),
                _age_bucket(veterans).alias("age_bucket"),
            )
            for row in (
                annotated.group_by("games_bucket", "age_bucket")
                .agg(pl.len().alias("rows"), pl.col("actual_games_played").mean().alias("games"))
                .iter_rows(named=True)
            ):
                if int(row["rows"]) >= MINIMUM_BUCKET_ROWS and row["games"] is not None:
                    pair[(str(row["games_bucket"]), str(row["age_bucket"]))] = scalar_float(
                        row["games"],
                    )
            for row in (
                annotated.group_by("games_bucket")
                .agg(pl.len().alias("rows"), pl.col("actual_games_played").mean().alias("games"))
                .iter_rows(named=True)
            ):
                if int(row["rows"]) >= MINIMUM_BUCKET_ROWS and row["games"] is not None:
                    single[str(row["games_bucket"])] = scalar_float(row["games"])
            default_games = scalar_float(veterans.get_column("actual_games_played").mean())

        no_prior_prior: dict[str, float] = {}
        default_no_prior = 0.0
        if others.height:
            annotated = others.with_columns(_draft_bucket(others).alias("draft_bucket"))
            for row in (
                annotated.group_by("draft_bucket")
                .agg(pl.len().alias("rows"), pl.col(TARGET_COLUMN).mean().alias("points"))
                .iter_rows(named=True)
            ):
                if int(row["rows"]) >= MINIMUM_BUCKET_ROWS and row["points"] is not None:
                    no_prior_prior[str(row["draft_bucket"])] = scalar_float(row["points"])
            default_no_prior = scalar_float(others.get_column(TARGET_COLUMN).median())
        elif train.height:
            default_no_prior = scalar_float(train.get_column(TARGET_COLUMN).median())

        return _B0Fit(
            shrinkage_games=shrinkage,
            position_rate=position_rate,
            expected_games_pair=pair,
            expected_games_by_availability=single,
            default_games=default_games,
            no_prior_prior=no_prior_prior,
            default_no_prior=default_no_prior,
        )

    def _predict(self, fitted: _B0Fit, frame: pl.DataFrame) -> Floats:
        if frame.height == 0:
            return np.zeros(0, dtype=np.float64)
        has_prior = _has_prior_production(frame).to_numpy()
        rate = (
            frame.get_column("prior_ppg_matched")
            .cast(pl.Float64)
            .fill_null(fitted.position_rate)
            .to_numpy()
        )
        games = frame.get_column("prev1_games").cast(pl.Float64).fill_null(0.0).to_numpy()
        if fitted.shrinkage_games > 0.0:
            weight = fitted.shrinkage_games
            rate = (games * rate + weight * fitted.position_rate) / (games + weight)

        availability = _games_bucket(frame).to_list()
        ages = _age_bucket(frame).to_list()
        expected = np.array(
            [
                fitted.expected_games_pair.get(
                    (str(bucket), str(age)),
                    fitted.expected_games_by_availability.get(str(bucket), fitted.default_games),
                )
                for bucket, age in zip(availability, ages, strict=True)
            ],
            dtype=np.float64,
        )
        veteran_prediction = rate * expected

        draft_buckets = _draft_bucket(frame).to_list()
        no_prior_prediction = np.array(
            [
                fitted.no_prior_prior.get(str(bucket), fitted.default_no_prior)
                for bucket in draft_buckets
            ],
            dtype=np.float64,
        )
        return np.where(has_prior, veteran_prediction, no_prior_prediction)

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: FitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        inner_fit = train.filter(pl.col("season").is_in(list(split.fit_seasons)))
        inner_residual = train.filter(pl.col("season").is_in(list(split.residual_seasons)))
        inner_actual = inner_residual.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()

        best_shrinkage = self.shrinkage_grid[0]
        best_error = float("inf")
        best_prediction = np.zeros(inner_actual.size, dtype=np.float64)
        for shrinkage in self.shrinkage_grid:
            prediction = self._predict(self._fit(inner_fit, shrinkage), inner_residual)
            error = (
                float(np.mean(np.abs(inner_actual - prediction)))
                if inner_actual.size
                else float("inf")
            )
            if error < best_error:
                best_shrinkage, best_error, best_prediction = shrinkage, error, prediction

        quantile_model = ResidualQuantiles.fit(
            inner_actual - best_prediction,
            best_prediction,
            context.levels,
        )

        fitted = self._fit(train, best_shrinkage)
        point = self._predict(fitted, validate)
        raw = quantile_model.apply(point)
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=repair_monotonicity(raw),
            raw_quantiles=raw,
            diagnostics={
                "selected_shrinkage_games": best_shrinkage,
                "inner_holdout_mae": round(best_error, 4),
                "fit": fitted.describe(),
                "inner_split": split.to_dict(),
                "residual_quantiles": quantile_model.describe(),
                "train_rows": train.height,
                "validation_rows": validate.height,
            },
        )


def _ridge_solve(x: Floats, y: Floats, alpha: float) -> tuple[Floats, float]:
    """Closed-form ridge on centred, standardized inputs; the intercept is never penalized."""
    if x.shape[1] == 0:
        return np.zeros(0, dtype=np.float64), float(np.mean(y)) if y.size else 0.0
    intercept = float(np.mean(y))
    centred = y - intercept
    gram = x.T @ x + alpha * np.eye(x.shape[1], dtype=np.float64)
    weights: Floats = np.linalg.solve(gram, x.T @ centred)
    return weights, intercept


class RidgeBaseline:
    """B1. An ordinary regularized linear model on the same core features."""

    model_id = "B1"

    def __init__(self, alphas: Sequence[float] = RIDGE_ALPHAS) -> None:
        self.alphas = tuple(alphas)

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": B1_VERSION,
            "family": "ridge regression (closed form, NumPy)",
            "alpha_grid": list(self.alphas),
            "alpha_selection": (
                "lowest MAE on an inner chronological split of the training window; the "
                "validation season is never consulted"
            ),
            "preprocessing": (
                "drop training-constant columns, median imputation with a missingness "
                "indicator per imputed column, standardization - all fitted on the training "
                "fold"
            ),
            "quantiles": "training-fold residuals from the same inner chronological split",
        }

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: FitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        inner_fit = train.filter(pl.col("season").is_in(list(split.fit_seasons)))
        inner_residual = train.filter(pl.col("season").is_in(list(split.residual_seasons)))

        inner_pre = FoldPreprocessor.fit(
            design_matrix(inner_fit, context.features),
            context.features,
        )
        inner_x = inner_pre.transform(design_matrix(inner_fit, context.features))
        inner_y = inner_fit.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        holdout_x = inner_pre.transform(design_matrix(inner_residual, context.features))
        holdout_y = inner_residual.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()

        best_alpha = self.alphas[0]
        best_error = float("inf")
        best_prediction = np.zeros(holdout_y.size, dtype=np.float64)
        for alpha in self.alphas:
            weights, intercept = _ridge_solve(inner_x, inner_y, alpha)
            prediction = (
                holdout_x @ weights + intercept
                if weights.size
                else np.full(
                    holdout_y.size,
                    intercept,
                    dtype=np.float64,
                )
            )
            error = (
                float(np.mean(np.abs(holdout_y - prediction)))
                if holdout_y.size
                else float(
                    "inf",
                )
            )
            if error < best_error:
                best_alpha, best_error, best_prediction = alpha, error, prediction

        quantile_model = ResidualQuantiles.fit(
            holdout_y - best_prediction,
            best_prediction,
            context.levels,
        )

        preprocessor = FoldPreprocessor.fit(
            design_matrix(train, context.features),
            context.features,
        )
        train_x = preprocessor.transform(design_matrix(train, context.features))
        train_y = train.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        weights, intercept = _ridge_solve(train_x, train_y, best_alpha)
        validate_x = preprocessor.transform(design_matrix(validate, context.features))
        point = (
            validate_x @ weights + intercept
            if weights.size
            else np.full(validate.height, intercept, dtype=np.float64)
        )
        raw = quantile_model.apply(point)
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=repair_monotonicity(raw),
            raw_quantiles=raw,
            diagnostics={
                "selected_alpha": best_alpha,
                "inner_holdout_mae": round(best_error, 4),
                "inner_split": split.to_dict(),
                "preprocessing": preprocessor.describe(),
                "residual_quantiles": quantile_model.describe(),
                "train_rows": train.height,
                "validation_rows": validate.height,
            },
        )
