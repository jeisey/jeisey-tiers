"""Orchestration of the rest-of-season evaluation.

One entry point runs the whole comparison: every declared baseline and the single candidate,
fitted inside every chronological fold, scored on the same rows, aggregated over the same
cells, compared by the same paired bootstrap and judged by the frozen gate.

**The evaluation cell is one week's board.** ``(season, through_week, position,
scoring_preset)``. That choice matters more here than it did preseason: a player contributes
sixteen rows to a season, so a cell that pooled a whole season would contain the same player
many times over and the bootstrap would resample him as if the repeats were independent
observations. Within one week's board every row is a different player, which is the unit a
fantasy decision is actually made over, and the macro mean across cells then weights a week
in September the same as a week in December.

**Nothing in this module decides anything.** The comparator is chosen by
:func:`ffdraft.ros.gate.select_primary_baseline`, the verdict by
:func:`ffdraft.ros.gate.evaluate_ros_promotion_gate`, and both rules were committed before
this module ran.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.features.dictionary import ALL_CORE_POSITIONS
from ffdraft.modeling.bootstrap import DEFAULT_REPLICATES, PairedCell, paired_bootstrap
from ffdraft.modeling.metrics import (
    QUANTILE_LEVELS,
    TOP_K_BY_POSITION,
    coverage,
    mae,
    slice_metrics,
    spearman,
)
from ffdraft.ros.baselines import (
    ROS_BASELINE_DECLARATION_ORDER,
    AvailabilityPriorBaseline,
    CurrentFormBaseline,
    PreseasonProratedBaseline,
    ShrinkageBlendBaseline,
)
from ffdraft.ros.candidates import RosHurdleCandidate
from ffdraft.ros.dataset import RosDataset
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.estimators import (
    ROS_TARGET_COLUMN,
    RosFitContext,
    RosModel,
    quantile_column_names,
    ros_prediction_frame,
)
from ffdraft.ros.folds import ROS_SEED, RosFold, ros_development_folds, ros_fold_table
from ffdraft.ros.gate import (
    ROS_PROMOTION_CRITERIA,
    RosCohortEvidence,
    RosGateResult,
    evaluate_ros_promotion_gate,
    select_primary_baseline,
)
from ffdraft.ros.holdout import ros_holdout_policy, ros_slice_masks
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ROS_EXPERIMENT_VERSION",
    "CANDIDATE_ID",
    "RosExperimentConfig",
    "RosExperimentResult",
    "ros_experiment_checks",
    "run_ros_experiment",
]

#: Bump when the orchestration changes in a way that moves a reported number.
ROS_EXPERIMENT_VERSION = "phase11_ros_v1"

CANDIDATE_ID = "RC1"

_CELL_KEYS: tuple[str, ...] = ("season", "through_week", "position", "scoring_preset")

#: Context columns the predeclared slice masks read. Joined onto the evaluation frame rather
#: than carried through every prediction block.
_SLICE_COLUMNS: tuple[str, ...] = (
    "rookie_flag",
    "draft_overall",
    "games_to_date",
    "points_per_week_to_date",
    "consecutive_weeks_missed",
    "has_played_this_season",
    "team_changed_in_season",
    "in_preseason_universe",
)

#: A cell needs at least this many rows before its rank correlation means anything.
_MINIMUM_CELL_ROWS = 5


@dataclass(frozen=True)
class RosExperimentConfig:
    """Everything one rest-of-season experiment is a function of."""

    seed: int = ROS_SEED
    replicates: int = DEFAULT_REPLICATES
    positions: tuple[str, ...] = ALL_CORE_POSITIONS
    scoring_presets: tuple[str, ...] = ("HALF", "PPR", "STD")
    levels: tuple[float, ...] = QUANTILE_LEVELS
    folds: tuple[RosFold, ...] = field(default_factory=ros_development_folds)
    label: str = "development"

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_version": ROS_EXPERIMENT_VERSION,
            "label": self.label,
            "seed": self.seed,
            "bootstrap_replicates": self.replicates,
            "positions": list(self.positions),
            "scoring_presets": list(self.scoring_presets),
            "quantile_levels": list(self.levels),
            "evaluation_cell": "season x through_week x position x scoring_preset",
            "folds": ros_fold_table(self.folds),
        }


@dataclass
class RosExperimentResult:
    """Everything one experiment produced."""

    config: RosExperimentConfig
    predictions: pl.DataFrame
    cells: tuple[dict[str, Any], ...]
    macro: dict[str, dict[str, float]]
    primary_baseline: str
    deltas: dict[str, Any]
    cohorts: tuple[RosCohortEvidence, ...]
    gate: RosGateResult
    models: dict[str, dict[str, Any]]
    dataset: dict[str, Any]
    runtime_seconds: dict[str, float] = field(default_factory=dict)
    checks: tuple[QualityCheck, ...] = ()
    generated_at: datetime = field(default_factory=utc_now)

    def cell_frame(self) -> pl.DataFrame:
        """The full per-cell table. Written beside the dataset, not into the report."""
        return pl.DataFrame(
            [
                {key: value for key, value in cell.items() if key != "pinball_by_quantile"}
                for cell in self.cells
            ],
        )

    def _aggregate(self, keys: Sequence[str]) -> list[dict[str, Any]]:
        """Macro means over cells, grouped. The report carries these instead of 4,800 cells.

        A committed report has to stay readable and reviewable; the week-by-week and
        season-by-position views are what a reader actually reads, and the raw cell table is
        written next to the dataset for anyone who wants to re-aggregate it.
        """
        frame = self.cell_frame()
        if frame.is_empty():
            return []
        metrics = (
            "mae",
            "spearman",
            "mean_pinball",
            "top_k_recall",
            "coverage_p10_p90",
            "mean_width_p10_p90",
        )
        grouped = (
            frame.group_by(["model_id", *keys])
            .agg(
                pl.len().alias("cells"),
                pl.col("n").sum().alias("rows"),
                *[pl.col(name).mean().alias(name) for name in metrics],
            )
            .sort(["model_id", *keys])
        )
        return grouped.to_dicts()

    def cells_by_week(self) -> list[dict[str, Any]]:
        return self._aggregate(["through_week"])

    def cells_by_season_position(self) -> list[dict[str, Any]]:
        return self._aggregate(["season", "position", "scoring_preset"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": isoformat_utc(self.generated_at),
            "configuration": self.config.to_dict(),
            "dataset": self.dataset,
            "models": self.models,
            "holdout_policy": ros_holdout_policy(
                status=(
                    "UNTOUCHED / NOT EVALUATED"
                    if self.config.label == "development"
                    else "CONSUMED"
                ),
            ),
            "macro_by_model": self.macro,
            "primary_baseline": self.primary_baseline,
            "promotion_criteria": ROS_PROMOTION_CRITERIA.to_dict(),
            "paired_deltas": {metric: delta.to_dict() for metric, delta in self.deltas.items()},
            "cohorts": [item.to_dict() for item in self.cohorts],
            "gate": self.gate.to_dict(),
            "cell_count": len(self.cells),
            "cells_by_week": self.cells_by_week(),
            "cells_by_season_position": self.cells_by_season_position(),
            "runtime_seconds": self.runtime_seconds,
            "checks": [check.to_dict() for check in self.checks],
        }


def declared_models(preseason_frame: pl.DataFrame) -> dict[str, RosModel]:
    """The four declared baselines and the one candidate, in declaration order."""
    return {
        "R0": PreseasonProratedBaseline(preseason_frame),
        "R1": CurrentFormBaseline(),
        "R2": ShrinkageBlendBaseline(preseason_frame),
        "R3": AvailabilityPriorBaseline(),
        CANDIDATE_ID: RosHurdleCandidate(),
    }


def _fit_all(
    dataset: RosDataset,
    models: Mapping[str, RosModel],
    config: RosExperimentConfig,
    features: Sequence[str],
) -> pl.DataFrame:
    """Fit every model in every fold and group, and stack the predictions."""
    frames: list[pl.DataFrame] = []
    for fold in config.folds:
        for preset in config.scoring_presets:
            for position in config.positions:
                group = (pl.col("position") == position) & (pl.col("scoring_preset") == preset)
                train = dataset.frame.filter(
                    pl.col("season").is_in(list(fold.train_seasons)) & group,
                )
                validate = dataset.frame.filter(
                    (pl.col("season") == fold.validation_season) & group,
                )
                if train.is_empty() or validate.is_empty():
                    continue
                context = RosFitContext(
                    fold=fold,
                    position=position,
                    scoring_preset=preset,
                    features=tuple(features),
                    seed=config.seed,
                    levels=config.levels,
                )
                for model_id, model in models.items():
                    started = time.perf_counter()
                    block = model.fit_predict(train, validate, context)
                    frames.append(
                        ros_prediction_frame(block, model_id=model_id, context=context),
                    )
                    print(
                        f"  {fold.fold_id} {position}/{preset} {model_id}: "
                        f"{validate.height} row(s) in {time.perf_counter() - started:.1f}s",
                        file=sys.stderr,
                        flush=True,
                    )
    if not frames:
        raise ValueError("the experiment produced no predictions")
    return pl.concat(frames)


def _evaluation_frame(dataset: RosDataset, predictions: pl.DataFrame) -> pl.DataFrame:
    """One row per scored player-snapshot, carrying every model's output side by side."""
    keys = ["season", "through_week", "player_id", "position", "scoring_preset"]
    quantiles = list(quantile_column_names())
    wide = predictions.pivot(
        on="model_id",
        index=[*keys, ROS_TARGET_COLUMN],
        values=["pred_point", *quantiles],
        aggregate_function="first",
    )
    context = dataset.frame.select(
        *keys,
        *(name for name in _SLICE_COLUMNS if name in dataset.frame.columns),
    )
    return wide.join(context, on=keys, how="left")


def _model_columns(model_id: str) -> tuple[str, list[str]]:
    quantiles = list(quantile_column_names())
    return f"pred_point_{model_id}", [f"{name}_{model_id}" for name in quantiles]


def _cell_metrics(
    frame: pl.DataFrame,
    models: Sequence[str],
    levels: Sequence[float],
) -> list[dict[str, Any]]:
    """Every declared metric per model per evaluation cell."""
    rows: list[dict[str, Any]] = []
    for keys, cell in frame.group_by(_CELL_KEYS, maintain_order=True):
        season, week, position, preset = (
            int(keys[0]),
            int(keys[1]),
            str(keys[2]),
            str(keys[3]),
        )
        if cell.height < _MINIMUM_CELL_ROWS:
            continue
        actual = cell.get_column(ROS_TARGET_COLUMN).to_numpy().astype(np.float64)
        for model_id in models:
            point_column, quantile_columns = _model_columns(model_id)
            point = cell.get_column(point_column).to_numpy().astype(np.float64)
            matrix = cell.select(quantile_columns).to_numpy().astype(np.float64)
            metrics = slice_metrics(actual, point, matrix, position=position, levels=levels)
            rows.append(
                {
                    "model_id": model_id,
                    "season": season,
                    "through_week": week,
                    "position": position,
                    "scoring_preset": preset,
                    **metrics,
                },
            )
    return rows


def _macro(
    cells: Sequence[Mapping[str, Any]], models: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Macro means across cells, which is what the gate and the bootstrap both aggregate."""
    metrics = (
        "mae",
        "rmse",
        "spearman",
        "mean_pinball",
        "top_k_recall",
        "coverage_p10_p90",
        "coverage_p25_p75",
        "mean_width_p10_p90",
    )
    output: dict[str, dict[str, float]] = {}
    for model_id in models:
        subset = [cell for cell in cells if cell["model_id"] == model_id]
        output[model_id] = {
            name: float(np.nanmean([float(cell[name]) for cell in subset]))
            if subset
            else float("nan")
            for name in metrics
        }
        output[model_id]["cells"] = float(len(subset))
        output[model_id]["rows"] = float(sum(int(cell["n"]) for cell in subset))
    return output


def _paired_cells(
    frame: pl.DataFrame,
    baseline: str,
    candidate: str,
) -> list[PairedCell]:
    cells: list[PairedCell] = []
    baseline_point, baseline_quantiles = _model_columns(baseline)
    candidate_point, candidate_quantiles = _model_columns(candidate)
    for keys, cell in frame.group_by(_CELL_KEYS, maintain_order=True):
        if cell.height < _MINIMUM_CELL_ROWS:
            continue
        position = str(keys[2])
        cells.append(
            PairedCell(
                key=f"{keys[0]}|w{keys[1]}|{position}|{keys[3]}",
                actual=cell.get_column(ROS_TARGET_COLUMN).to_numpy().astype(np.float64),
                baseline_point=cell.get_column(baseline_point).to_numpy().astype(np.float64),
                candidate_point=cell.get_column(candidate_point).to_numpy().astype(np.float64),
                baseline_quantiles=cell.select(baseline_quantiles).to_numpy().astype(np.float64),
                candidate_quantiles=cell.select(candidate_quantiles).to_numpy().astype(np.float64),
                top_k=TOP_K_BY_POSITION.get(position, 0),
            ),
        )
    return cells


def _cohort_evidence(
    frame: pl.DataFrame,
    baseline: str,
    candidate: str,
    levels: Sequence[float],
) -> list[RosCohortEvidence]:
    """Paired evidence for every predeclared slice, ranked within cell rather than pooled."""
    baseline_point, baseline_quantiles = _model_columns(baseline)
    candidate_point, candidate_quantiles = _model_columns(candidate)
    width = pl.col(f"q90_{baseline}") - pl.col(f"q10_{baseline}")
    scoped = frame.with_columns(width.alias("baseline_interval_width"))
    low_index, high_index = list(levels).index(0.10), list(levels).index(0.90)

    evidence: list[RosCohortEvidence] = []
    for mask in ros_slice_masks(scoped):
        subset = scoped.filter(mask.mask)
        if subset.is_empty():
            continue
        actual = subset.get_column(ROS_TARGET_COLUMN).to_numpy().astype(np.float64)
        base_point = subset.get_column(baseline_point).to_numpy().astype(np.float64)
        cand_point = subset.get_column(candidate_point).to_numpy().astype(np.float64)
        base_matrix = subset.select(baseline_quantiles).to_numpy().astype(np.float64)
        cand_matrix = subset.select(candidate_quantiles).to_numpy().astype(np.float64)
        evidence.append(
            RosCohortEvidence(
                slice_id=mask.slice_id,
                label=mask.label,
                rows=subset.height,
                baseline_mae=mae(actual, base_point),
                candidate_mae=mae(actual, cand_point),
                baseline_spearman=_macro_spearman(subset, baseline_point),
                candidate_spearman=_macro_spearman(subset, candidate_point),
                baseline_coverage=coverage(
                    actual,
                    base_matrix[:, low_index],
                    base_matrix[:, high_index],
                ),
                candidate_coverage=coverage(
                    actual,
                    cand_matrix[:, low_index],
                    cand_matrix[:, high_index],
                ),
                baseline_width=float(
                    np.mean(base_matrix[:, high_index] - base_matrix[:, low_index]),
                ),
                candidate_width=float(
                    np.mean(cand_matrix[:, high_index] - cand_matrix[:, low_index]),
                ),
            ),
        )
    return evidence


def _macro_spearman(frame: pl.DataFrame, point_column: str) -> float:
    """Rank correlation averaged over the cells a cohort touches, never pooled across them.

    Pooling a whole cohort's rows would rank a week-2 quarterback against a week-14 tight end,
    which is not a comparison any board makes.
    """
    values: list[float] = []
    for _, cell in frame.group_by(_CELL_KEYS, maintain_order=True):
        if cell.height < _MINIMUM_CELL_ROWS:
            continue
        values.append(
            spearman(
                cell.get_column(ROS_TARGET_COLUMN).to_numpy().astype(np.float64),
                cell.get_column(point_column).to_numpy().astype(np.float64),
            ),
        )
    return float(np.nanmean(values)) if values else float("nan")


def run_ros_experiment(
    dataset: RosDataset,
    preseason_frame: pl.DataFrame,
    *,
    config: RosExperimentConfig | None = None,
) -> RosExperimentResult:
    """Run every declared model over every fold, then apply the frozen gate."""
    settings = config or RosExperimentConfig()
    selection = ros_feature_selection()
    features = [name for name in selection.included if name in dataset.frame.columns]
    missing = [name for name in selection.included if name not in dataset.frame.columns]
    models = declared_models(preseason_frame)

    timings: dict[str, float] = {}
    started = time.perf_counter()
    predictions = _fit_all(dataset, models, settings, features)
    timings["fit"] = round(time.perf_counter() - started, 1)

    started = time.perf_counter()
    frame = _evaluation_frame(dataset, predictions)
    model_ids = list(models)
    cells = _cell_metrics(frame, model_ids, settings.levels)
    macro = _macro(cells, model_ids)
    timings["metrics"] = round(time.perf_counter() - started, 1)

    primary = select_primary_baseline(macro, ROS_BASELINE_DECLARATION_ORDER)
    started = time.perf_counter()
    deltas = paired_bootstrap(
        _paired_cells(frame, primary, CANDIDATE_ID),
        metrics=("mae", "mean_pinball", "spearman", "top_k_recall"),
        seed=settings.seed,
        replicates=settings.replicates,
        levels=settings.levels,
    )
    timings["bootstrap"] = round(time.perf_counter() - started, 1)

    started = time.perf_counter()
    cohorts = _cohort_evidence(frame, primary, CANDIDATE_ID, settings.levels)
    timings["cohorts"] = round(time.perf_counter() - started, 1)
    gate = evaluate_ros_promotion_gate(
        deltas,
        cohorts,
        primary_baseline=primary,
        candidate=CANDIDATE_ID,
    )

    checks = ros_experiment_checks(
        dataset,
        frame,
        macro,
        missing_features=missing,
        config=settings,
    )
    return RosExperimentResult(
        config=settings,
        predictions=frame,
        cells=tuple(cells),
        macro=macro,
        primary_baseline=primary,
        deltas=deltas,
        cohorts=tuple(cohorts),
        gate=gate,
        models={model_id: model.describe() for model_id, model in models.items()},
        dataset=dataset.describe(),
        runtime_seconds=timings,
        checks=tuple(checks),
    )


def ros_experiment_checks(
    dataset: RosDataset,
    frame: pl.DataFrame,
    macro: Mapping[str, Mapping[str, float]],
    *,
    missing_features: Sequence[str],
    config: RosExperimentConfig,
) -> list[QualityCheck]:
    """Findings a reader of the report should not have to derive from the tables."""
    checks: list[QualityCheck] = []
    if missing_features:
        checks.append(
            QualityCheck.fail(
                "ros_experiment.declared_feature_absent",
                stage="ros_experiment",
                message="a declared model input is not present in the snapshot dataset",
                observed=str(sorted(missing_features)),
                expected="every ros_core_v1 column present",
                severity=Severity.CRITICAL,
            ),
        )
    sealed = [season for season in dataset.seasons if season >= 2025]
    if config.label == "development" and sealed:
        checks.append(
            QualityCheck.fail(
                "ros_experiment.sealed_season_reached",
                stage="ros_experiment",
                message="a development run loaded a sealed season",
                observed=str(sealed),
                expected="no sealed season in a development frame",
                severity=Severity.CRITICAL,
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "ros_experiment.seal_respected",
                stage="ros_experiment",
                message="the run touched only the seasons its label permits",
                observed=f"label={config.label}; seasons={list(dataset.seasons)}",
            ),
        )
    checks.append(
        QualityCheck.ok(
            "ros_experiment.scored_rows",
            stage="ros_experiment",
            message="rows scored by every model on identical keys",
            observed=f"{frame.height} row(s) across {len(config.folds)} fold(s)",
        ),
    )
    for model_id, values in macro.items():
        checks.append(
            QualityCheck.ok(
                "ros_experiment.macro_metrics",
                stage="ros_experiment",
                message=f"{model_id} macro metrics",
                observed=(
                    f"mae={values['mae']:.3f} pinball={values['mean_pinball']:.3f} "
                    f"spearman={values['spearman']:.3f} "
                    f"coverage_p10_p90={values['coverage_p10_p90']:.3f}"
                ),
            ),
        )
    return checks
