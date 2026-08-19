"""The Phase-3 experiment: folds, models, metrics, uncertainty, gate, decision.

One entry point runs the whole thing, and it runs the same way every time: the seed, the
fold table, the feature selection, the model definitions and the promotion criteria are all
inputs recorded in the report rather than choices made along the way.

Order matters and is enforced by construction:

1. the final holdout is already absent from the dataset (:mod:`ffdraft.modeling.dataset`);
2. the feature selection is audited for development-era support before anything is fitted;
3. every model is fitted per fold, per position, per scoring preset, on training seasons
   only;
4. metrics are computed per cell, then aggregated macro-first so a large position cannot
   quietly outvote a small one;
5. paired bootstrap intervals are computed on identical resampled rows;
6. the frozen gate in :mod:`ffdraft.modeling.gate` is applied last, to numbers it did not
   help produce.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from ffdraft.contracts import CheckStatus, QualityCheck, Severity
from ffdraft.modeling.baselines import NaivePriorProductionBaseline, RidgeBaseline
from ffdraft.modeling.bootstrap import (
    DEFAULT_REPLICATES,
    BootstrapDelta,
    PairedCell,
    paired_bootstrap,
)
from ffdraft.modeling.candidates import LightGbmQuantileCandidate
from ffdraft.modeling.dataset import TARGET_COLUMN, ModelingDataset
from ffdraft.modeling.estimators import (
    FitContext,
    IntrinsicModel,
    prediction_frame,
    quantile_columns,
)
from ffdraft.modeling.features import audit_era_stability
from ffdraft.modeling.folds import (
    DEFAULT_SEED,
    DEVELOPMENT_VALIDATION_SEASONS,
    Fold,
    FoldKind,
    WindowPolicy,
    development_folds,
    diagnostic_folds,
    final_holdout_fold,
    fold_table,
)
from ffdraft.modeling.gate import (
    PROMOTION_CRITERIA,
    GateResult,
    PositionalEvidence,
    PromotionCriteria,
    WindowDecision,
    evaluate_promotion_gate,
    select_training_window,
)
from ffdraft.modeling.holdout import (
    FinalEvalAuthorization,
    final_holdout_policy,
    slice_masks,
)
from ffdraft.modeling.metrics import QUANTILE_LEVELS, slice_metrics

__all__ = [
    "EXPERIMENT_VERSION",
    "ExperimentConfig",
    "ExperimentResult",
    "FinalHoldoutResult",
    "aggregate_cells",
    "build_models",
    "run_experiment",
    "run_final_holdout_evaluation",
]

#: Bump when the harness changes in a way that makes an older report incomparable.
EXPERIMENT_VERSION = "phase3_intrinsic_v1"

_METRIC_KEYS: tuple[str, ...] = (
    "mae",
    "rmse",
    "spearman",
    "kendall_tau_b",
    "top_k_recall",
    "mean_pinball",
    "coverage_p10_p90",
    "coverage_p25_p75",
    "mean_width_p10_p90",
    "mean_width_p25_p75",
    "crossing_rate_raw",
    "crossing_magnitude_raw",
)


@dataclass(frozen=True)
class ExperimentConfig:
    """Everything that makes a run reproducible."""

    windows: tuple[WindowPolicy, ...] = (WindowPolicy.W1, WindowPolicy.W2)
    model_ids: tuple[str, ...] = ("B0", "B1", "Q1")
    seed: int = DEFAULT_SEED
    bootstrap_replicates: int = DEFAULT_REPLICATES
    validation_seasons: tuple[int, ...] = DEVELOPMENT_VALIDATION_SEASONS
    include_w1_diagnostic_folds: bool = True
    levels: tuple[float, ...] = QUANTILE_LEVELS
    criteria: PromotionCriteria = PROMOTION_CRITERIA

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "windows": [str(window) for window in self.windows],
            "models": list(self.model_ids),
            "seed": self.seed,
            "bootstrap_replicates": self.bootstrap_replicates,
            "validation_seasons": list(self.validation_seasons),
            "include_w1_diagnostic_folds": self.include_w1_diagnostic_folds,
            "quantile_levels": list(self.levels),
        }


def build_models(model_ids: Sequence[str]) -> dict[str, IntrinsicModel]:
    """Construct the requested models. The registry is explicit rather than discovered."""
    registry: dict[str, IntrinsicModel] = {
        "B0": NaivePriorProductionBaseline(),
        "B1": RidgeBaseline(),
        "Q1": LightGbmQuantileCandidate(),
    }
    unknown = sorted(set(model_ids) - set(registry))
    if unknown:
        raise ValueError(f"unknown model id(s): {unknown}")
    return {model_id: registry[model_id] for model_id in model_ids}


@dataclass
class ExperimentResult:
    """Everything one run produced, ready for serialization."""

    config: ExperimentConfig
    dataset: dict[str, Any]
    feature_selection: dict[str, Any]
    feature_coverage: dict[str, Any]
    folds: list[dict[str, Any]]
    model_definitions: dict[str, Any]
    cells: list[dict[str, Any]]
    aggregates: list[dict[str, Any]]
    positional: list[dict[str, Any]]
    seasonal: list[dict[str, Any]]
    scoring: list[dict[str, Any]]
    deltas: dict[str, dict[str, Any]]
    window_decision: WindowDecision
    gate_results: list[GateResult]
    selection: dict[str, Any]
    fit_diagnostics: list[dict[str, Any]]
    checks: list[QualityCheck] = field(default_factory=list)
    predictions: pl.DataFrame | None = None
    runtime_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return any(result.passed for result in self.gate_results)


def _cell_records(
    dataset: ModelingDataset,
    models: Mapping[str, IntrinsicModel],
    folds: Sequence[Fold],
    config: ExperimentConfig,
) -> tuple[list[dict[str, Any]], list[pl.DataFrame], list[dict[str, Any]]]:
    """Fit every model on every fold x position x scoring cell and score it."""
    features = tuple(dataset.selection.included)
    cells: list[dict[str, Any]] = []
    predictions: list[pl.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    positions = sorted(set(dataset.frame.get_column("position").to_list()))
    presets = sorted(set(dataset.frame.get_column("scoring_preset").to_list()))

    for fold in folds:
        train_all, validate_all = dataset.fold_frames(fold)
        for position in positions:
            for preset in presets:
                mask = (pl.col("position") == position) & (pl.col("scoring_preset") == preset)
                train = train_all.filter(mask)
                validate = validate_all.filter(mask)
                if train.height == 0 or validate.height == 0:
                    continue
                context = FitContext(
                    fold=fold,
                    position=position,
                    scoring_preset=preset,
                    features=features,
                    seed=config.seed,
                    levels=config.levels,
                )
                actual = validate.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
                for model_id, model in models.items():
                    block = model.fit_predict(train, validate, context)
                    metrics = slice_metrics(
                        actual,
                        block.point,
                        block.quantiles,
                        position=position,
                        levels=config.levels,
                        raw_quantiles=block.raw_quantiles,
                    )
                    cells.append(
                        {
                            "window_policy": str(fold.window),
                            "fold_kind": str(fold.kind),
                            "fold_id": fold.fold_id,
                            "model_id": model_id,
                            "validation_season": fold.validation_season,
                            "train_start_season": fold.train_start_season,
                            "train_end_season": fold.train_end_season,
                            "position": position,
                            "scoring_preset": preset,
                            "train_rows": train.height,
                            **metrics,
                        },
                    )
                    predictions.append(
                        prediction_frame(block, model_id=model_id, context=context),
                    )
                    diagnostics.append(
                        {
                            "window_policy": str(fold.window),
                            "fold_id": fold.fold_id,
                            "model_id": model_id,
                            "position": position,
                            "scoring_preset": preset,
                            **block.diagnostics,
                        },
                    )
    return cells, predictions, diagnostics


def _mean(values: Sequence[float]) -> float:
    finite = [value for value in values if value == value]  # drop NaN
    return float(np.mean(finite)) if finite else float("nan")


def _weighted(values: Sequence[float], weights: Sequence[int]) -> float:
    pairs = [(v, w) for v, w in zip(values, weights, strict=True) if v == v and w > 0]
    if not pairs:
        return float("nan")
    total = sum(weight for _, weight in pairs)
    return float(sum(value * weight for value, weight in pairs) / total)


def aggregate_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    by: Sequence[str] = ("window_policy", "model_id"),
    kind: str = str(FoldKind.DEVELOPMENT),
) -> list[dict[str, Any]]:
    """Macro and row-weighted aggregates over evaluation cells.

    Macro first, always. Row-weighted numbers are emitted alongside as diagnostics, because
    WR and RB cells carry two to three times the rows of QB and TE ones and a pooled mean
    would let them decide a positional question on their own.
    """
    selected = [cell for cell in cells if cell["fold_kind"] == kind]
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for cell in selected:
        groups.setdefault(tuple(cell[key] for key in by), []).append(cell)

    records: list[dict[str, Any]] = []
    for key, members in sorted(groups.items(), key=lambda item: [str(part) for part in item[0]]):
        record: dict[str, Any] = dict(zip(by, key, strict=True))
        record["cells"] = len(members)
        record["rows"] = int(sum(int(member["n"]) for member in members))
        weights = [int(member["n"]) for member in members]
        for metric in _METRIC_KEYS:
            values = [float(member[metric]) for member in members]
            record[f"macro_{metric}"] = _mean(values)
            record[f"weighted_{metric}"] = _weighted(values, weights)
        records.append(record)
    return records


def _paired_cells(
    predictions: pl.DataFrame,
    *,
    baseline: tuple[str, str],
    candidate: tuple[str, str],
    kind_folds: Sequence[str],
) -> list[PairedCell]:
    """Align two (model, window) prediction sets row for row, cell by cell."""
    quantiles = list(quantile_columns())
    keys = ["validation_season", "position", "scoring_preset", "player_id"]

    def select(model_id: str, window: str) -> pl.DataFrame:
        return (
            predictions.filter(
                (pl.col("model_id") == model_id)
                & (pl.col("window_policy") == window)
                & (pl.col("fold_id").is_in(list(kind_folds))),
            )
            .with_columns(pl.col("season").alias("validation_season"))
            .select([*keys, TARGET_COLUMN, "pred_point", *quantiles])
        )

    left = select(*baseline)
    right = select(*candidate)
    joined = left.join(right, on=keys, how="inner", suffix="_cand")
    cells: list[PairedCell] = []
    for (season, position, preset), block in joined.group_by(
        ["validation_season", "position", "scoring_preset"],
        maintain_order=True,
    ):
        block = block.sort("player_id")
        cells.append(
            PairedCell(
                key=f"{season}|{position}|{preset}",
                actual=block.get_column(TARGET_COLUMN).to_numpy().astype(np.float64),
                baseline_point=block.get_column("pred_point").to_numpy().astype(np.float64),
                candidate_point=block.get_column("pred_point_cand").to_numpy().astype(np.float64),
                baseline_quantiles=block.select(quantiles).to_numpy().astype(np.float64),
                candidate_quantiles=block.select([f"{name}_cand" for name in quantiles])
                .to_numpy()
                .astype(np.float64),
            ),
        )
    return sorted(cells, key=lambda cell: cell.key)


def _positional_evidence(
    cells: Sequence[Mapping[str, Any]],
    *,
    window: str,
    baseline_id: str,
    candidate_id: str,
) -> list[PositionalEvidence]:
    per_position = aggregate_cells(
        [cell for cell in cells if cell["window_policy"] == window],
        by=("model_id", "position"),
    )
    indexed = {(record["model_id"], record["position"]): record for record in per_position}
    positions = sorted({position for _, position in indexed})
    evidence: list[PositionalEvidence] = []
    for position in positions:
        baseline = indexed.get((baseline_id, position))
        candidate = indexed.get((candidate_id, position))
        if baseline is None or candidate is None:
            continue
        evidence.append(
            PositionalEvidence(
                position=position,
                baseline_mae=float(baseline["macro_mae"]),
                candidate_mae=float(candidate["macro_mae"]),
                baseline_spearman=float(baseline["macro_spearman"]),
                candidate_spearman=float(candidate["macro_spearman"]),
                candidate_coverage_p10_p90=float(candidate["macro_coverage_p10_p90"]),
            ),
        )
    return evidence


def run_experiment(
    dataset: ModelingDataset,
    *,
    config: ExperimentConfig | None = None,
) -> ExperimentResult:
    """Run the whole Phase-3 development experiment over an already-sealed dataset."""
    started = time.monotonic()
    settings = config or ExperimentConfig()
    checks: list[QualityCheck] = list(dataset.checks)

    if not dataset.sealed:
        checks.append(
            QualityCheck.fail(
                "phase3.holdout_present_in_development_run",
                stage="phase3_experiment",
                message=(
                    "the modelling frame still contains a sealed season; a development "
                    "experiment must never see it"
                ),
                observed=f"seasons={list(dataset.seasons)}",
            ),
        )
        raise ValueError("refusing to run a development experiment over unsealed data")

    era_checks, coverage = audit_era_stability(
        dataset.audit_frame,
        selection=dataset.selection,
        development_seasons=settings.validation_seasons,
    )
    checks.extend(era_checks)

    models = build_models(settings.model_ids)
    folds: list[Fold] = []
    for window in settings.windows:
        folds.extend(development_folds(window, settings.validation_seasons))
    if settings.include_w1_diagnostic_folds and WindowPolicy.W1 in settings.windows:
        folds.extend(diagnostic_folds(WindowPolicy.W1))

    cells, prediction_blocks, diagnostics = _cell_records(dataset, models, folds, settings)
    predictions = pl.concat(prediction_blocks) if prediction_blocks else pl.DataFrame()

    development_fold_ids = [fold.fold_id for fold in folds if fold.kind is FoldKind.DEVELOPMENT]
    aggregates = aggregate_cells(cells)
    positional = aggregate_cells(cells, by=("window_policy", "model_id", "position"))
    seasonal = aggregate_cells(cells, by=("window_policy", "model_id", "validation_season"))
    scoring = aggregate_cells(cells, by=("window_policy", "model_id", "scoring_preset"))

    baseline_id = settings.criteria.primary_baseline
    deltas: dict[str, dict[str, Any]] = {}
    gate_results: list[GateResult] = []
    delta_objects: dict[str, Mapping[str, BootstrapDelta]] = {}

    for window in settings.windows:
        window_folds = [
            fold_id for fold_id in development_fold_ids if fold_id.startswith(str(window))
        ]
        for model_id in settings.model_ids:
            if model_id == baseline_id:
                continue
            paired = _paired_cells(
                predictions,
                baseline=(baseline_id, str(window)),
                candidate=(model_id, str(window)),
                kind_folds=window_folds,
            )
            if not paired:
                continue
            result = paired_bootstrap(
                paired,
                seed=settings.seed,
                replicates=settings.bootstrap_replicates,
                levels=settings.levels,
            )
            key = f"{model_id}_vs_{baseline_id}@{window}"
            delta_objects[key] = result
            deltas[key] = {name: delta.to_dict() for name, delta in result.items()}
            gate_results.append(
                evaluate_promotion_gate(
                    model_id=model_id,
                    window=str(window),
                    deltas=result,
                    positional=_positional_evidence(
                        cells,
                        window=str(window),
                        baseline_id=baseline_id,
                        candidate_id=model_id,
                    ),
                    criteria=settings.criteria,
                ),
            )

    window_decision = _decide_window(predictions, settings, development_fold_ids, deltas)
    selection = _select_model(gate_results, aggregates, window_decision, settings)

    checks.append(
        QualityCheck.ok(
            "phase3.final_holdout_untouched",
            stage="phase3_experiment",
            message="no sealed season entered training, tuning or evaluation",
            observed=f"evaluated seasons={list(settings.validation_seasons)}",
        ),
    )

    return ExperimentResult(
        config=settings,
        dataset=dataset.describe(),
        feature_selection=dataset.selection.to_dict(),
        feature_coverage=coverage,
        folds=fold_table(folds),
        model_definitions={model_id: model.describe() for model_id, model in models.items()},
        cells=cells,
        aggregates=aggregates,
        positional=positional,
        seasonal=seasonal,
        scoring=scoring,
        deltas=deltas,
        window_decision=window_decision,
        gate_results=gate_results,
        selection=selection,
        fit_diagnostics=diagnostics,
        checks=checks,
        predictions=predictions,
        runtime_seconds=round(time.monotonic() - started, 2),
    )


def _decide_window(
    predictions: pl.DataFrame,
    settings: ExperimentConfig,
    development_fold_ids: Sequence[str],
    deltas: dict[str, dict[str, Any]],
) -> WindowDecision:
    """Compare the windows on the common folds with the same candidate family."""
    if WindowPolicy.W1 not in settings.windows or WindowPolicy.W2 not in settings.windows:
        return WindowDecision(
            selected=WindowPolicy.W2,
            decisive=False,
            rationale="only one window was evaluated; the conservative default stands",
        )
    comparison_model = settings.model_ids[-1]
    w2_folds = [
        fold_id for fold_id in development_fold_ids if fold_id.startswith(str(WindowPolicy.W2))
    ]
    w1_folds = [
        fold_id for fold_id in development_fold_ids if fold_id.startswith(str(WindowPolicy.W1))
    ]
    # Both sides predict the same validation rows, so the pairing is exact; W2 is passed as
    # the "baseline" so a negative delta reads as "W1 is better".
    paired = _paired_cells(
        predictions,
        baseline=(comparison_model, str(WindowPolicy.W2)),
        candidate=(comparison_model, str(WindowPolicy.W1)),
        kind_folds=[*w1_folds, *w2_folds],
    )
    if not paired:
        return WindowDecision(
            selected=WindowPolicy.W2,
            decisive=False,
            rationale="no paired window cells were available; the conservative default stands",
        )
    result = paired_bootstrap(
        paired,
        seed=settings.seed,
        replicates=settings.bootstrap_replicates,
        levels=settings.levels,
    )
    deltas[f"W1_vs_W2@{comparison_model}"] = {
        name: delta.to_dict() for name, delta in result.items()
    }
    return select_training_window(result, criteria=settings.criteria)


def _select_model(
    gate_results: Sequence[GateResult],
    aggregates: Sequence[Mapping[str, Any]],
    window_decision: WindowDecision,
    settings: ExperimentConfig,
) -> dict[str, Any]:
    """Window first, then the passing candidate with the best probabilistic quality."""
    window = str(window_decision.selected)
    passing = [result for result in gate_results if result.passed and result.window == window]
    indexed = {(record["window_policy"], record["model_id"]): record for record in aggregates}
    if not passing:
        return {
            "window_policy": window,
            "promoted_model": None,
            "rule": (
                "the candidate with the lowest macro mean pinball loss among those passing "
                "the frozen gate on the selected window"
            ),
            "passed_any": False,
            "note": "no candidate passed the frozen gate on the selected window",
        }
    ranked = sorted(
        passing,
        key=lambda result: (
            float(indexed[(window, result.model_id)]["macro_mean_pinball"]),
            float(indexed[(window, result.model_id)]["macro_mae"]),
        ),
    )
    winner = ranked[0]
    record = indexed[(window, winner.model_id)]
    return {
        "window_policy": window,
        "promoted_model": winner.model_id,
        "rule": (
            "the candidate with the lowest macro mean pinball loss among those passing the "
            "frozen gate on the selected window; ties broken on macro MAE"
        ),
        "passed_any": True,
        "candidates_passing": [result.model_id for result in ranked],
        "macro_mae": float(record["macro_mae"]),
        "macro_mean_pinball": float(record["macro_mean_pinball"]),
        "macro_spearman": float(record["macro_spearman"]),
        "criteria_version": settings.criteria.version,
    }


def experiment_checks(result: ExperimentResult) -> list[QualityCheck]:
    """The checks a caller should gate on, including the promotion outcome itself."""
    checks = list(result.checks)
    if result.passed:
        winners = [item.model_id for item in result.gate_results if item.passed]
        checks.append(
            QualityCheck.ok(
                "phase3.promotion_gate",
                stage="phase3_experiment",
                message="at least one candidate passed the frozen promotion gate",
                observed=", ".join(sorted(set(winners))),
            ),
        )
    else:
        checks.append(
            QualityCheck.fail(
                "phase3.promotion_gate",
                stage="phase3_experiment",
                message=(
                    "no candidate passed the frozen promotion gate; Phase 3 is not complete "
                    "and the gate may not be weakened after the fact"
                ),
                observed="; ".join(
                    f"{item.model_id}@{item.window}: {'; '.join(item.failures)}"
                    for item in result.gate_results
                ),
            ),
        )
    return checks


def holdout_status(result: ExperimentResult) -> dict[str, Any]:
    """The final-holdout declaration, with the status this run leaves it in."""
    untouched = all(
        check.status is CheckStatus.PASS
        for check in result.checks
        if check.check_id == "phase3.final_holdout_untouched"
    )
    return final_holdout_policy(
        status="UNTOUCHED / NOT EVALUATED" if untouched else "CONSUMED",
    )


@dataclass
class FinalHoldoutResult:
    """A final-holdout evaluation. Producing one consumes the holdout."""

    config: ExperimentConfig
    window: WindowPolicy
    authorization_reason: str
    folds: list[dict[str, Any]]
    model_definitions: dict[str, Any]
    cells: list[dict[str, Any]]
    aggregates: list[dict[str, Any]]
    slices: list[dict[str, Any]]
    checks: list[QualityCheck] = field(default_factory=list)
    predictions: pl.DataFrame | None = None
    runtime_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "final_holdout",
            "experiment_version": EXPERIMENT_VERSION,
            "configuration": self.config.to_dict(),
            "window_policy": str(self.window),
            "authorization_reason": self.authorization_reason,
            "folds": self.folds,
            "models": self.model_definitions,
            "metrics_by_cell": self.cells,
            "aggregates": self.aggregates,
            "predeclared_slices": self.slices,
            "final_holdout": final_holdout_policy(status="CONSUMED"),
            "checks": [check.to_dict() for check in self.checks],
            "runtime_seconds": self.runtime_seconds,
        }


def run_final_holdout_evaluation(
    dataset: ModelingDataset,
    *,
    authorization: FinalEvalAuthorization,
    window: WindowPolicy,
    config: ExperimentConfig | None = None,
) -> FinalHoldoutResult:
    """Evaluate the frozen candidate family on the sealed season. Phase 4 only.

    This is the other side of the seal, and it is deliberately a separate entry point: a
    development run cannot reach it by passing a different flag to the same function. It
    reports the primary full-universe result first and every predeclared diagnostic slice
    beside it, because the slices exist to explain the primary number, never to replace it.
    """
    started = time.monotonic()
    settings = config or ExperimentConfig()
    if dataset.sealed:
        raise ValueError(
            "the modelling frame has no sealed season in it; load it with the same "
            "authorization before running a final-holdout evaluation",
        )
    fold = final_holdout_fold(window, authorization=authorization)
    models = build_models(settings.model_ids)
    cells, prediction_blocks, _ = _cell_records(dataset, models, [fold], settings)
    predictions = pl.concat(prediction_blocks) if prediction_blocks else pl.DataFrame()

    holdout_frame = dataset.frame.filter(pl.col("season") == fold.validation_season)
    slices = _slice_metrics(predictions, holdout_frame, settings)

    checks = [
        QualityCheck.fail(
            "phase3.final_holdout_consumed",
            stage="phase3_final_holdout",
            message=(
                "the final holdout was evaluated; it is no longer an untouched holdout and "
                "no later model-design decision may be made against it"
            ),
            observed=authorization.reason,
            severity=Severity.WARNING,
        ),
    ]
    return FinalHoldoutResult(
        config=settings,
        window=window,
        authorization_reason=authorization.reason,
        folds=fold_table([fold]),
        model_definitions={model_id: model.describe() for model_id, model in models.items()},
        cells=cells,
        aggregates=aggregate_cells(cells, kind=str(FoldKind.FINAL_HOLDOUT)),
        slices=slices,
        checks=checks,
        predictions=predictions,
        runtime_seconds=round(time.monotonic() - started, 2),
    )


def _slice_metrics(
    predictions: pl.DataFrame,
    holdout_frame: pl.DataFrame,
    settings: ExperimentConfig,
) -> list[dict[str, Any]]:
    """Metrics for every predeclared holdout slice, primary first."""
    if predictions.is_empty():
        return []
    context_columns = [
        name
        for name in (
            "eligibility_basis",
            "depth_context_state",
            "rookie_flag",
            "has_prior_season_stats",
            "prev1_games",
        )
        if name in holdout_frame.columns
    ]
    joined = predictions.join(
        holdout_frame.select(["season", "player_id", "scoring_preset", *context_columns]),
        on=["season", "player_id", "scoring_preset"],
        how="inner",
    )
    records: list[dict[str, Any]] = []
    quantiles = list(quantile_columns())
    for mask in slice_masks(joined):
        block = joined.filter(mask.mask)
        if block.is_empty():
            continue
        for (model_id,), model_block in block.group_by(["model_id"], maintain_order=True):
            for (position,), position_block in model_block.group_by(
                ["position"],
                maintain_order=True,
            ):
                actual = position_block.get_column(TARGET_COLUMN).to_numpy().astype(np.float64)
                metrics = slice_metrics(
                    actual,
                    position_block.get_column("pred_point").to_numpy().astype(np.float64),
                    position_block.select(quantiles).to_numpy().astype(np.float64),
                    position=str(position),
                    levels=settings.levels,
                )
                records.append(
                    {
                        "slice_id": mask.slice_id,
                        "slice_kind": str(mask.kind),
                        "slice_label": mask.label,
                        "model_id": str(model_id),
                        "position": str(position),
                        **metrics,
                    },
                )
    return records
