"""The four declared rest-of-season baselines.

`docs/RELEASE2_ROADMAP.md` 11.4 names them, and all four are implemented and reported. The
comparator the candidate must actually beat is chosen from among them by the frozen rule in
:mod:`ffdraft.ros.gate` - lowest development macro pinball loss - so the gate cannot be made
easy by picking a weak one.

``R0`` — preseason expectation, prorated
    Release 1's preseason expectation for the same player-season, multiplied by the share of
    the scored horizon still ahead. The expectation is Phase 3's B0 baseline - prior-season
    points per game times the games a player with that availability history typically plays -
    refitted inside each ROS fold on the same training seasons, so R0 never sees a season the
    ROS model has not seen either. A player with no preseason row has no preseason
    expectation and gets zero, which is exactly what a preseason board said about him.

``R1`` — current-season rate, extended
    Points per appearance so far times an expected remaining-games count built from the
    player's own appearance rate and his team's remaining schedule. Nothing from before the
    season enters it, so R0 and R1 are the two pure-information-source extremes.

``R2`` — shrinkage blend
    ``w * R0 + (1 - w) * R1`` with ``w = k / (k + games_to_date)``. Early in the season the
    prior dominates; by week ten the current season does. ``k`` is chosen inside the fold
    from a tiny predeclared grid on an inner chronological split - never against the
    validation season.

``R3`` — position and availability prior
    The training-fold mean of remaining points within ``(position, games-played band,
    remaining-weeks band)``. It knows nothing about the individual player, which makes it the
    floor a personalised model has to clear, and the natural comparator for the sparse-history
    cohorts 11.3 asks about.

All four emit the same five quantiles, estimated from out-of-sample training residuals on an
inner chronological split (:mod:`ffdraft.modeling.preprocessing`). Giving a baseline a
fabricated fixed-width interval would make the probabilistic comparison meaningless.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.baselines import NaivePriorProductionBaseline
from ffdraft.modeling.estimators import FitContext, PredictionBlock, repair_monotonicity
from ffdraft.modeling.folds import Fold, WindowPolicy
from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.modeling.preprocessing import ResidualQuantiles, inner_chronological_split
from ffdraft.ros.estimators import ROS_TARGET_COLUMN, RosFitContext, as_floats
from ffdraft.scoring.horizon import fantasy_horizon

__all__ = [
    "AvailabilityPriorBaseline",
    "CurrentFormBaseline",
    "PreseasonProratedBaseline",
    "ROS_BASELINE_DECLARATION_ORDER",
    "R0_VERSION",
    "R1_VERSION",
    "R2_VERSION",
    "R3_VERSION",
    "SHRINKAGE_GRID",
    "ShrinkageBlendBaseline",
    "preseason_modelling_frame",
]

Floats = NDArray[np.float64]

R0_VERSION = "r0_preseason_prorated_v1"
R1_VERSION = "r1_current_rate_v1"
R2_VERSION = "r2_shrinkage_blend_v1"
R3_VERSION = "r3_availability_prior_v1"

#: Declaration order, used as the final tie-break when the gate picks its comparator.
ROS_BASELINE_DECLARATION_ORDER: tuple[str, ...] = ("R0", "R1", "R2", "R3")

#: Candidate shrinkage weights for R2, in games: a player with exactly this many appearances
#: is pulled halfway from the preseason prior towards his current-season rate. The grid is
#: tiny and predeclared, and the value is chosen on an inner chronological split of the
#: *training* window, never against the validation season.
SHRINKAGE_GRID: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)

#: Bands R3 pools over. Coarse on purpose: a prior with a hundred cells is not a prior.
_GAMES_BANDS: tuple[int, ...] = (0, 1, 3, 6, 10)
_REMAINING_BANDS: tuple[int, ...] = (1, 3, 6, 10)


def _band(values: Floats, edges: Sequence[int]) -> NDArray[np.int64]:
    return np.digitize(values, np.asarray(edges[1:], dtype=np.float64), right=False).astype(
        np.int64,
    )


def _quantiles_from_residuals(
    residual_point: Floats,
    residual_actual: Floats,
    point: Floats,
    levels: Sequence[float],
) -> tuple[Floats, Floats]:
    """Predictive quantiles from out-of-sample training residuals, then made monotone."""
    residuals = residual_actual - residual_point
    model = ResidualQuantiles.fit(residuals, residual_point, levels)
    raw = model.apply(point)
    return raw, repair_monotonicity(raw)


def _horizon_share(frame: pl.DataFrame) -> Floats:
    """Share of the season's scored horizon still ahead of each row's cutoff."""
    remaining = as_floats(frame, "remaining_horizon_weeks")
    seasons = frame.get_column("season").to_list()
    lengths = np.asarray(
        [float(fantasy_horizon(int(season)).week_count) for season in seasons],
        dtype=np.float64,
    )
    return np.divide(remaining, lengths, out=np.zeros_like(remaining), where=lengths > 0)


def _expected_remaining_games(frame: pl.DataFrame) -> Floats:
    """A deliberately simple remaining-games estimate: appearance rate times games left."""
    share = as_floats(frame, "games_share_to_date")
    scheduled = frame.get_column("team_remaining_scheduled_games").cast(pl.Float64)
    weeks = as_floats(frame, "remaining_horizon_weeks")
    games_left = scheduled.fill_null(0.0).to_numpy().astype(np.float64)
    games_left = np.where(games_left > 0.0, games_left, weeks)
    return share * games_left


class PreseasonProratedBaseline:
    """R0: Release 1's preseason expectation, prorated over the remaining horizon."""

    model_id = "R0"

    def __init__(self, preseason_frame: pl.DataFrame) -> None:
        self._preseason = preseason_frame
        self._inner = NaivePriorProductionBaseline()

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": R0_VERSION,
            "family": "preseason season-total expectation x remaining share of the horizon",
            "preseason_model": self._inner.describe(),
            "proration": "expectation x remaining_horizon_weeks / horizon week count",
            "players_without_a_preseason_row": "predicted zero",
            "quantiles": "out-of-sample training residuals, stratified by predicted level",
        }

    def preseason_expectation(
        self,
        context: RosFitContext,
        seasons: Sequence[int],
        validation_season: int,
    ) -> pl.DataFrame:
        """Fit B0 on the fold's training seasons and predict the validation season."""
        scope = self._preseason.filter(
            (pl.col("position") == context.position)
            & (pl.col("scoring_preset") == context.scoring_preset),
        )
        train = scope.filter(pl.col("season").is_in(list(seasons)))
        validate = scope.filter(pl.col("season") == validation_season)
        if train.is_empty() or validate.is_empty():
            return pl.DataFrame(
                schema={"player_id": pl.String, "preseason_expected_points": pl.Float64},
            )
        inner_context = FitContext(
            fold=Fold(
                window=WindowPolicy.W2,
                train_start_season=min(seasons),
                train_end_season=max(seasons),
                validation_season=validation_season,
            ),
            position=context.position,
            scoring_preset=context.scoring_preset,
            features=(),
            seed=context.seed,
            levels=context.levels,
        )
        block = self._inner.fit_predict(train, validate, inner_context)
        return block.keys.select("player_id").with_columns(
            pl.Series("preseason_expected_points", block.point, dtype=pl.Float64),
        )

    def prorated_point(
        self,
        frame: pl.DataFrame,
        expectation: pl.DataFrame,
    ) -> Floats:
        if expectation.is_empty():
            return np.zeros(frame.height, dtype=np.float64)
        joined = frame.select("player_id").join(expectation, on="player_id", how="left")
        expected = joined.get_column("preseason_expected_points").fill_null(0.0)
        return expected.to_numpy().astype(np.float64) * _horizon_share(frame)

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        residual_rows = train.filter(pl.col("season").is_in(list(split.residual_seasons)))
        residual_expectation = pl.concat(
            [
                self.preseason_expectation(context, split.fit_seasons, season)
                for season in split.residual_seasons
            ],
            how="vertical",
        )
        residual_point = self.prorated_point(residual_rows, residual_expectation)
        residual_actual = as_floats(residual_rows, ROS_TARGET_COLUMN)

        expectation = self.preseason_expectation(
            context,
            context.fold.train_seasons,
            context.fold.validation_season,
        )
        point = self.prorated_point(validate, expectation)
        raw, quantiles = _quantiles_from_residuals(
            residual_point,
            residual_actual,
            point,
            context.levels,
        )
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={
                "residual_seasons": list(split.residual_seasons),
                "preseason_rows_matched": int(np.count_nonzero(point != 0.0)),
            },
        )


class CurrentFormBaseline:
    """R1: current-season points per appearance times a simple remaining-games estimate."""

    model_id = "R1"

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": R1_VERSION,
            "family": "points per appearance to date x expected remaining games",
            "expected_remaining_games": (
                "games_share_to_date x the observed team's remaining scheduled games, "
                "falling back to remaining horizon weeks when no team has been observed"
            ),
            "players_without_an_appearance": "predicted zero",
            "quantiles": "out-of-sample training residuals, stratified by predicted level",
        }

    @staticmethod
    def _point(frame: pl.DataFrame) -> Floats:
        ppg = as_floats(frame, "ppg_to_date")
        return ppg * _expected_remaining_games(frame)

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        residual_rows = train.filter(pl.col("season").is_in(list(split.residual_seasons)))
        point = self._point(validate)
        raw, quantiles = _quantiles_from_residuals(
            self._point(residual_rows),
            as_floats(residual_rows, ROS_TARGET_COLUMN),
            point,
            context.levels,
        )
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={"residual_seasons": list(split.residual_seasons)},
        )


@dataclass(frozen=True, slots=True)
class _BlendFit:
    shrinkage: float
    grid: tuple[float, ...]
    scores: tuple[float, ...]


class ShrinkageBlendBaseline:
    """R2: a games-weighted blend of the preseason prior and the current-season rate."""

    model_id = "R2"

    def __init__(self, preseason_frame: pl.DataFrame) -> None:
        self._r0 = PreseasonProratedBaseline(preseason_frame)
        self._r1 = CurrentFormBaseline()

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": R2_VERSION,
            "family": "w * R0 + (1 - w) * R1 with w = k / (k + games_to_date)",
            "shrinkage_grid": list(SHRINKAGE_GRID),
            "shrinkage_selection": (
                "chosen inside the fold on an inner chronological split by mean absolute "
                "error; never against the validation season"
            ),
            "components": {"prior": R0_VERSION, "current": R1_VERSION},
            "quantiles": "out-of-sample training residuals, stratified by predicted level",
        }

    @staticmethod
    def _blend(prior: Floats, current: Floats, games: Floats, shrinkage: float) -> Floats:
        weight = shrinkage / (shrinkage + games)
        return weight * prior + (1.0 - weight) * current

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        residual_rows = train.filter(pl.col("season").is_in(list(split.residual_seasons)))
        residual_expectation = pl.concat(
            [
                self._r0.preseason_expectation(context, split.fit_seasons, season)
                for season in split.residual_seasons
            ],
            how="vertical",
        )
        residual_prior = self._r0.prorated_point(residual_rows, residual_expectation)
        residual_current = self._r1._point(residual_rows)
        residual_games = as_floats(residual_rows, "games_to_date")
        residual_actual = as_floats(residual_rows, ROS_TARGET_COLUMN)

        scores = [
            float(
                np.mean(
                    np.abs(
                        residual_actual
                        - self._blend(
                            residual_prior,
                            residual_current,
                            residual_games,
                            shrinkage,
                        ),
                    ),
                ),
            )
            if residual_actual.size
            else float("inf")
            for shrinkage in SHRINKAGE_GRID
        ]
        chosen = SHRINKAGE_GRID[int(np.argmin(scores))] if residual_actual.size else 2.0
        fit = _BlendFit(shrinkage=chosen, grid=SHRINKAGE_GRID, scores=tuple(scores))

        expectation = self._r0.preseason_expectation(
            context,
            context.fold.train_seasons,
            context.fold.validation_season,
        )
        point = self._blend(
            self._r0.prorated_point(validate, expectation),
            self._r1._point(validate),
            as_floats(validate, "games_to_date"),
            chosen,
        )
        residual_point = self._blend(
            residual_prior,
            residual_current,
            residual_games,
            chosen,
        )
        raw, quantiles = _quantiles_from_residuals(
            residual_point,
            residual_actual,
            point,
            context.levels,
        )
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={
                "shrinkage": fit.shrinkage,
                "grid": list(fit.grid),
                "inner_mae_by_shrinkage": [round(value, 4) for value in fit.scores],
                "residual_seasons": list(split.residual_seasons),
            },
        )


class AvailabilityPriorBaseline:
    """R3: a training-fold mean by position, appearances so far and weeks remaining."""

    model_id = "R3"

    def describe(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": R3_VERSION,
            "family": "mean remaining points by (games-played band, remaining-weeks band)",
            "games_bands": list(_GAMES_BANDS),
            "remaining_bands": list(_REMAINING_BANDS),
            "fallback": "the group's overall training mean when a cell is empty",
            "quantiles": "out-of-sample training residuals, stratified by predicted level",
        }

    @staticmethod
    def _cells(frame: pl.DataFrame) -> NDArray[np.int64]:
        games = _band(as_floats(frame, "games_to_date"), _GAMES_BANDS)
        remaining = _band(as_floats(frame, "remaining_horizon_weeks"), _REMAINING_BANDS)
        return games * len(_REMAINING_BANDS) + remaining

    def _table(self, frame: pl.DataFrame) -> tuple[dict[int, float], float]:
        cells = self._cells(frame)
        actual = as_floats(frame, ROS_TARGET_COLUMN)
        overall = float(np.mean(actual)) if actual.size else 0.0
        table: dict[int, float] = {}
        for cell in np.unique(cells):
            table[int(cell)] = float(np.mean(actual[cells == cell]))
        return table, overall

    @staticmethod
    def _apply(
        frame: pl.DataFrame,
        table: dict[int, float],
        overall: float,
        cells: NDArray[np.int64],
    ) -> Floats:
        del frame
        return np.asarray([table.get(int(cell), overall) for cell in cells], dtype=np.float64)

    def fit_predict(
        self,
        train: pl.DataFrame,
        validate: pl.DataFrame,
        context: RosFitContext,
    ) -> PredictionBlock:
        split = inner_chronological_split(context.fold.train_seasons)
        fit_rows = train.filter(pl.col("season").is_in(list(split.fit_seasons)))
        residual_rows = train.filter(pl.col("season").is_in(list(split.residual_seasons)))

        inner_table, inner_overall = self._table(fit_rows)
        residual_point = self._apply(
            residual_rows,
            inner_table,
            inner_overall,
            self._cells(residual_rows),
        )
        table, overall = self._table(train)
        point = self._apply(validate, table, overall, self._cells(validate))
        raw, quantiles = _quantiles_from_residuals(
            residual_point,
            as_floats(residual_rows, ROS_TARGET_COLUMN),
            point,
            context.levels,
        )
        return PredictionBlock(
            keys=validate,
            point=point,
            quantiles=quantiles,
            raw_quantiles=raw,
            diagnostics={
                "cells": len(table),
                "overall_mean": round(overall, 4),
                "residual_seasons": list(split.residual_seasons),
            },
        )


def preseason_modelling_frame(
    features: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    seasons: Sequence[int],
    authorization: object | None = None,
) -> pl.DataFrame:
    """The Phase-3 modelling frame R0 and R2 fit their preseason component on.

    Built with the same joiner Release 1 uses, so the preseason expectation inside a
    rest-of-season baseline is the *same* number Release 1 would have produced rather than a
    re-implementation of it.

    ``seasons`` is the set the rest-of-season dataset actually carries. In development that
    excludes the sealed season, so no Release 1 seal is touched at all. Reaching the sealed
    season requires a :class:`~ffdraft.ros.holdout.RosFinalEvalAuthorization`, which is
    translated into the Release 1 authorization here with a recorded reason - opening the
    rest-of-season holdout necessarily opens the preseason feature rows behind it, and that
    should be visible in both reports rather than in neither.
    """
    from ffdraft.modeling.dataset import build_modeling_frame
    from ffdraft.modeling.holdout import (
        FINAL_EVAL_CONFIRMATION_TOKEN,
        FinalEvalAuthorization,
        is_sealed,
    )

    wanted = [int(season) for season in seasons]
    scoped_features = features.filter(pl.col("season").is_in(wanted))
    scoped_labels = labels.filter(pl.col("season").is_in(wanted))

    inner: FinalEvalAuthorization | None = None
    if any(is_sealed(season) for season in wanted):
        if authorization is None:
            raise HoldoutSealError(
                "the rest-of-season baselines were asked for a sealed preseason season "
                "without a RosFinalEvalAuthorization",
            )
        inner = FinalEvalAuthorization(
            confirmation=FINAL_EVAL_CONFIRMATION_TOKEN,
            reason=(
                "preseason feature rows behind the rest-of-season final holdout; authorized "
                f"by the ROS holdout: {getattr(authorization, 'reason', '')}"
            ),
        )
    return build_modeling_frame(scoped_features, scoped_labels, authorization=inner).frame
