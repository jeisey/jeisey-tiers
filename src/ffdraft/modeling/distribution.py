"""Phase 4, stage B: choosing the production predictive distribution.

Three questions, asked in one run and answered in a fixed order by the rules ADR-030 froze
before any of these numbers existed:

1. **How should crossing quantiles be repaired, and do the intervals need calibrating?**
   ``A0`` is Q1's raw output projected onto the monotone cone; ``A1`` adds a fold-fitted
   per-level residual shift. ``phase4_calibration_v1`` decides.
2. **Does horizon normalization help?** ``AH`` is the same architecture trained against
   fantasy points per horizon week, the one predeclared sensitivity for the 2021 fold whose
   training window is entirely 16-week seasons. ``phase4_horizon_v1`` decides.
3. **Does separating availability from performance beat predicting the total directly?**
   ``CB`` is the hurdle model Phase 3 left unbuilt. ``phase4_candidate_v1`` decides.

The order is not cosmetic. Each stage runs the *winner* of the previous one, so the horizon
sensitivity is measured against the calibration that will actually ship and Candidate B is
measured against a fully calibrated Candidate A rather than against a strawman. That also
means each stage costs only what it must: the variants that lost are not carried forward.

``B0`` and ``Q1`` are fitted alongside as reference rows. B0 is the project's permanent
baseline; Q1 is the Phase-3 promoted form, sorted rather than projected, so the report can
answer "what did replacing the sort with a projection actually do?" from measurements rather
than from reasoning.

Everything here runs on development folds 2020-2024 under window W1. The sealed 2025 season
is absent from the frame by construction (:mod:`ffdraft.modeling.dataset`), so no stage of
this study could reach it even by mistake.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.contracts import CheckStatus, QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.modeling.baselines import NaivePriorProductionBaseline
from ffdraft.modeling.bootstrap import DEFAULT_REPLICATES, BootstrapDelta, paired_bootstrap
from ffdraft.modeling.calibration import (
    CalibrationStrategy,
    HorizonNormalizedTarget,
    IdentityTarget,
    MonotoneOnly,
    ResidualShiftCalibration,
    TargetScale,
)
from ffdraft.modeling.candidates import (
    HURDLE_COMPOSITION_DRAWS,
    AvailabilityPerformanceCandidate,
    CalibratedQuantileCandidate,
    LightGbmQuantileCandidate,
)
from ffdraft.modeling.dataset import ModelingDataset
from ffdraft.modeling.estimators import IntrinsicModel, quantile_columns
from ffdraft.modeling.experiment import aggregate_cells, cell_records, paired_cells
from ffdraft.modeling.folds import (
    DEFAULT_SEED,
    DEVELOPMENT_VALIDATION_SEASONS,
    Fold,
    WindowPolicy,
    development_folds,
    fold_table,
)
from ffdraft.modeling.metrics import QUANTILE_LEVELS, crossing_rate
from ffdraft.modeling.rules import (
    CALIBRATION_ACCEPTANCE,
    PHASE4_RULES_VERSION,
    CalibrationEvidence,
    Decision,
    HorizonEvidence,
    PairedDelta,
    PositionalCalibration,
    all_rules,
    evaluate_calibration_choice,
    evaluate_candidate_choice,
    evaluate_horizon_choice,
)
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "DISTRIBUTION_STUDY_VERSION",
    "OOF_PREDICTIONS_FILE",
    "DistributionConfig",
    "DistributionStudyResult",
    "run_distribution_study",
    "write_distribution_report",
]

#: Bump when the study's construction changes in a way that makes an older report
#: incomparable.
DISTRIBUTION_STUDY_VERSION = "phase4_distribution_v1"

OOF_PREDICTIONS_FILE = "oof_predictions.parquet"

_BOOTSTRAP_METRICS: tuple[str, ...] = ("mae", "mean_pinball", "spearman", "top_k_recall")


@dataclass(frozen=True)
class DistributionConfig:
    """Everything that makes the study reproducible."""

    window: WindowPolicy = WindowPolicy.W1
    validation_seasons: tuple[int, ...] = DEVELOPMENT_VALIDATION_SEASONS
    seed: int = DEFAULT_SEED
    bootstrap_replicates: int = DEFAULT_REPLICATES
    levels: tuple[float, ...] = QUANTILE_LEVELS
    composition_draws: int = HURDLE_COMPOSITION_DRAWS
    include_references: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_version": DISTRIBUTION_STUDY_VERSION,
            "rules_version": PHASE4_RULES_VERSION,
            "window_policy": str(self.window),
            "validation_seasons": list(self.validation_seasons),
            "seed": self.seed,
            "bootstrap_replicates": self.bootstrap_replicates,
            "quantile_levels": list(self.levels),
            "hurdle_composition_draws": self.composition_draws,
            "include_references": self.include_references,
        }

    def folds(self) -> tuple[Fold, ...]:
        return development_folds(self.window, self.validation_seasons)


@dataclass
class DistributionStudyResult:
    """Everything the study produced, ready for serialization."""

    config: DistributionConfig
    dataset: dict[str, Any]
    feature_selection: dict[str, Any]
    folds: list[dict[str, Any]]
    model_definitions: dict[str, Any]
    cells: list[dict[str, Any]]
    aggregates: list[dict[str, Any]]
    positional: list[dict[str, Any]]
    seasonal: list[dict[str, Any]]
    scoring: list[dict[str, Any]]
    deltas: dict[str, dict[str, Any]]
    calibration_decision: Decision
    horizon_decision: Decision
    candidate_decision: Decision
    selected: dict[str, Any]
    fit_diagnostics: list[dict[str, Any]]
    checks: list[QualityCheck] = field(default_factory=list)
    predictions: pl.DataFrame | None = None
    runtime_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return all(not check.blocking for check in self.checks)


# ---------------------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------------------


def _macro(cells: Sequence[Mapping[str, Any]], key: str, **filters: Any) -> float:
    values = [
        float(cell[key])
        for cell in cells
        if all(cell.get(name) == value for name, value in filters.items())
        and cell.get(key) is not None
        and float(cell[key]) == float(cell[key])
    ]
    return float(np.mean(values)) if values else float("nan")


def _positional_calibration(
    positional: Sequence[Mapping[str, Any]],
    model_id: str,
) -> tuple[PositionalCalibration, ...]:
    return tuple(
        PositionalCalibration(
            position=str(row["position"]),
            coverage_p10_p90=float(row["macro_coverage_p10_p90"]),
            coverage_p25_p75=float(row["macro_coverage_p25_p75"]),
        )
        for row in sorted(positional, key=lambda item: str(item["position"]))
        if row["model_id"] == model_id
    )


def _calibration_evidence(
    cells: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
    positional: Sequence[Mapping[str, Any]],
    model_id: str,
) -> CalibrationEvidence:
    row = next(item for item in aggregates if item["model_id"] == model_id)
    return CalibrationEvidence(
        variant_id=model_id,
        macro_mean_pinball=float(row["macro_mean_pinball"]),
        macro_mae=float(row["macro_mae"]),
        coverage_p10_p90=float(row["macro_coverage_p10_p90"]),
        coverage_p25_p75=float(row["macro_coverage_p25_p75"]),
        mean_width_p10_p90=float(row["macro_mean_width_p10_p90"]),
        crossing_rate_raw=float(row["macro_crossing_rate_raw"]),
        crossing_rate_post=_macro(cells, "crossing_rate_post", model_id=model_id),
        positional=_positional_calibration(positional, model_id),
    )


def _paired(
    predictions: pl.DataFrame,
    *,
    baseline: str,
    candidate: str,
    window: str,
    fold_ids: Sequence[str],
    config: DistributionConfig,
) -> dict[str, BootstrapDelta]:
    cells = paired_cells(
        predictions,
        baseline=(baseline, window),
        candidate=(candidate, window),
        kind_folds=list(fold_ids),
    )
    if not cells:
        return {}
    return paired_bootstrap(
        cells,
        metrics=_BOOTSTRAP_METRICS,
        seed=config.seed,
        replicates=config.bootstrap_replicates,
        levels=config.levels,
    )


def _as_rule_deltas(deltas: Mapping[str, BootstrapDelta]) -> dict[str, PairedDelta]:
    return {
        name: PairedDelta(name, delta.delta, delta.ci_low, delta.ci_high)
        for name, delta in deltas.items()
    }


def _post_crossing_by_cell(predictions: pl.DataFrame) -> dict[tuple[str, str, str, str], float]:
    """Post-processing crossing rate for every (model, fold, position, scoring) cell."""
    columns = list(quantile_columns())
    rates: dict[tuple[str, str, str, str], float] = {}
    grouped = predictions.group_by(["model_id", "fold_id", "position", "scoring_preset"])
    for key, block in grouped:
        model_id, fold_id, position, preset = (str(part) for part in key)
        rates[(model_id, fold_id, position, preset)] = crossing_rate(
            block.select(columns).to_numpy().astype(np.float64),
        )
    return rates


def _attach_post_crossing(
    cells: list[dict[str, Any]],
    predictions: pl.DataFrame,
) -> list[dict[str, Any]]:
    rates = _post_crossing_by_cell(predictions)
    for cell in cells:
        key = (
            str(cell["model_id"]),
            str(cell["fold_id"]),
            str(cell["position"]),
            str(cell["scoring_preset"]),
        )
        cell["crossing_rate_post"] = rates.get(key, float("nan"))
    return cells


def _positional_regressions(
    positional: Sequence[Mapping[str, Any]],
    *,
    reference: str,
    candidate: str,
) -> tuple[dict[str, float], dict[str, float]]:
    indexed = {(row["model_id"], row["position"]): row for row in positional}
    positions = sorted({str(position) for _, position in indexed})
    mae_regression: dict[str, float] = {}
    rank_regression: dict[str, float] = {}
    for position in positions:
        base = indexed.get((reference, position))
        cand = indexed.get((candidate, position))
        if base is None or cand is None:
            continue
        base_mae = float(base["macro_mae"])
        mae_regression[position] = (
            (float(cand["macro_mae"]) - base_mae) / base_mae if base_mae else 0.0
        )
        rank_regression[position] = float(base["macro_spearman"]) - float(cand["macro_spearman"])
    return mae_regression, rank_regression


# ---------------------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------------------


@dataclass
class _Stage:
    """One measured batch of models, accumulated into the study's tables."""

    cells: list[dict[str, Any]] = field(default_factory=list)
    frames: list[pl.DataFrame] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    definitions: dict[str, Any] = field(default_factory=dict)

    @property
    def predictions(self) -> pl.DataFrame:
        return pl.concat(self.frames) if self.frames else pl.DataFrame()

    def run(
        self,
        dataset: ModelingDataset,
        models: Mapping[str, IntrinsicModel],
        folds: Sequence[Fold],
        config: DistributionConfig,
    ) -> None:
        from ffdraft.modeling.experiment import ExperimentConfig

        settings = ExperimentConfig(
            windows=(config.window,),
            model_ids=tuple(models),
            seed=config.seed,
            bootstrap_replicates=config.bootstrap_replicates,
            validation_seasons=config.validation_seasons,
            include_w1_diagnostic_folds=False,
            levels=config.levels,
        )
        cells, frames, diagnostics = cell_records(dataset, models, folds, settings)
        block = pl.concat(frames) if frames else pl.DataFrame()
        self.cells.extend(_attach_post_crossing(cells, block))
        self.frames.extend(frames)
        self.diagnostics.extend(diagnostics)
        self.definitions.update(
            {model_id: model.describe() for model_id, model in models.items()},
        )


def run_distribution_study(
    dataset: ModelingDataset,
    *,
    config: DistributionConfig | None = None,
) -> DistributionStudyResult:
    """Run stage B and apply the three frozen rules in their declared order."""
    started = time.monotonic()
    settings = config or DistributionConfig()
    if not dataset.sealed:
        raise ValueError(
            "refusing to run the Phase-4 distribution study over unsealed data; the final "
            "holdout must not be visible to any development stage",
        )
    folds = settings.folds()
    fold_ids = [fold.fold_id for fold in folds]
    window = str(settings.window)
    checks: list[QualityCheck] = list(dataset.checks)
    stage = _Stage()

    # -- 1. calibration -----------------------------------------------------------------
    first: dict[str, IntrinsicModel] = {
        "A0": CalibratedQuantileCandidate("A0", calibration=MonotoneOnly()),
        "A1": CalibratedQuantileCandidate("A1", calibration=ResidualShiftCalibration()),
    }
    if settings.include_references:
        first = {
            "B0": NaivePriorProductionBaseline(),
            "Q1": LightGbmQuantileCandidate(),
            **first,
        }
    stage.run(dataset, first, folds, settings)
    aggregates = aggregate_cells(stage.cells, by=("model_id",))
    positional = aggregate_cells(stage.cells, by=("model_id", "position"))
    calibration_decision = _decide_calibration(
        stage.cells,
        aggregates,
        positional,
    )
    calibration: CalibrationStrategy = (
        ResidualShiftCalibration() if calibration_decision.selected == "A1" else MonotoneOnly()
    )
    selected_model_id = calibration_decision.selected

    # -- 2. horizon sensitivity ---------------------------------------------------------
    horizon_model = CalibratedQuantileCandidate(
        "AH",
        calibration=calibration,
        target=HorizonNormalizedTarget(),
    )
    stage.run(dataset, {"AH": horizon_model}, folds, settings)
    deltas: dict[str, dict[str, Any]] = {}
    horizon_deltas = _paired(
        stage.predictions,
        baseline=selected_model_id,
        candidate="AH",
        window=window,
        fold_ids=fold_ids,
        config=settings,
    )
    deltas[f"AH_vs_{selected_model_id}"] = {
        name: delta.to_dict() for name, delta in horizon_deltas.items()
    }
    seasonal = aggregate_cells(stage.cells, by=("model_id", "validation_season"))
    horizon_decision = _decide_horizon(
        horizon_deltas,
        seasonal,
        baseline_id=selected_model_id,
    )
    if horizon_decision.selected == "AH":
        selected_model_id = "AH"
        target: TargetScale = HorizonNormalizedTarget()
    else:
        target = IdentityTarget()

    # -- 3. Candidate B -----------------------------------------------------------------
    candidate_b = AvailabilityPerformanceCandidate(
        calibration=calibration,
        composition_draws=settings.composition_draws,
        seed_material=("candidate_b", DISTRIBUTION_STUDY_VERSION, settings.seed),
    )
    stage.run(dataset, {"CB": candidate_b}, folds, settings)
    aggregates = aggregate_cells(stage.cells, by=("model_id",))
    positional = aggregate_cells(stage.cells, by=("model_id", "position"))
    seasonal = aggregate_cells(stage.cells, by=("model_id", "validation_season"))
    scoring = aggregate_cells(stage.cells, by=("model_id", "scoring_preset"))

    candidate_deltas = _paired(
        stage.predictions,
        baseline=selected_model_id,
        candidate="CB",
        window=window,
        fold_ids=fold_ids,
        config=settings,
    )
    deltas[f"CB_vs_{selected_model_id}"] = {
        name: delta.to_dict() for name, delta in candidate_deltas.items()
    }
    mae_regression, rank_regression = _positional_regressions(
        positional,
        reference=selected_model_id,
        candidate="CB",
    )
    candidate_decision = _decide_candidate(
        candidate_deltas,
        stage.cells,
        aggregates,
        positional,
        reference_id=selected_model_id,
        mae_regression=mae_regression,
        rank_regression=rank_regression,
    )
    final_model_id = candidate_decision.selected

    # Reference deltas against the permanent baseline, reported rather than decisive.
    if settings.include_references:
        for model_id in ("Q1", final_model_id):
            reference_deltas = _paired(
                stage.predictions,
                baseline="B0",
                candidate=model_id,
                window=window,
                fold_ids=fold_ids,
                config=settings,
            )
            if reference_deltas:
                deltas[f"{model_id}_vs_B0"] = {
                    name: delta.to_dict() for name, delta in reference_deltas.items()
                }

    selected = _selected_architecture(
        final_model_id,
        calibration=calibration,
        target=target,
        candidate_b=candidate_b,
        aggregates=aggregates,
        cells=stage.cells,
    )
    checks.extend(
        _study_checks(
            calibration_decision,
            horizon_decision,
            candidate_decision,
            selected=selected,
            selected_evidence=_calibration_evidence(
                stage.cells,
                aggregates,
                positional,
                final_model_id,
            ),
            cells=stage.cells,
        ),
    )

    predictions = stage.predictions
    return DistributionStudyResult(
        config=settings,
        dataset=dataset.describe(),
        feature_selection=dataset.selection.to_dict(),
        folds=fold_table(folds),
        model_definitions=stage.definitions,
        cells=stage.cells,
        aggregates=aggregates,
        positional=positional,
        seasonal=seasonal,
        scoring=scoring,
        deltas=deltas,
        calibration_decision=calibration_decision,
        horizon_decision=horizon_decision,
        candidate_decision=candidate_decision,
        selected=selected,
        fit_diagnostics=stage.diagnostics,
        checks=checks,
        predictions=predictions,
        runtime_seconds=round(time.monotonic() - started, 2),
    )


def _decide_calibration(
    cells: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
    positional: Sequence[Mapping[str, Any]],
) -> Decision:
    return evaluate_calibration_choice(
        _calibration_evidence(cells, aggregates, positional, "A0"),
        _calibration_evidence(cells, aggregates, positional, "A1"),
    )


def _decide_horizon(
    deltas: Mapping[str, BootstrapDelta],
    seasonal: Sequence[Mapping[str, Any]],
    *,
    baseline_id: str,
) -> Decision:
    def by_season(model_id: str) -> dict[int, float]:
        return {
            int(row["validation_season"]): float(row["macro_mae"])
            for row in seasonal
            if row["model_id"] == model_id
        }

    return evaluate_horizon_choice(
        HorizonEvidence(
            deltas=_as_rule_deltas(deltas),
            baseline_mae_by_season=by_season(baseline_id),
            candidate_mae_by_season=by_season("AH"),
        ),
        baseline_id=baseline_id,
        candidate_id="AH",
    )


def _decide_candidate(
    deltas: Mapping[str, BootstrapDelta],
    cells: Sequence[Mapping[str, Any]],
    aggregates: Sequence[Mapping[str, Any]],
    positional: Sequence[Mapping[str, Any]],
    *,
    reference_id: str,
    mae_regression: Mapping[str, float],
    rank_regression: Mapping[str, float],
) -> Decision:
    return evaluate_candidate_choice(
        deltas=_as_rule_deltas(deltas),
        reference=_calibration_evidence(cells, aggregates, positional, reference_id),
        candidate=_calibration_evidence(cells, aggregates, positional, "CB"),
        positional_mae_regression=mae_regression,
        positional_rank_regression=rank_regression,
        reference_id=reference_id,
        candidate_id="CB",
    )


def _selected_architecture(
    model_id: str,
    *,
    calibration: CalibrationStrategy,
    target: TargetScale,
    candidate_b: AvailabilityPerformanceCandidate,
    aggregates: Sequence[Mapping[str, Any]],
    cells: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    row = next(item for item in aggregates if item["model_id"] == model_id)
    family = (
        "availability x performance hurdle"
        if model_id == "CB"
        else "direct-total LightGBM quantile regression"
    )
    definition = (
        candidate_b.describe()
        if model_id == "CB"
        else CalibratedQuantileCandidate(
            model_id,
            calibration=calibration,
            target=target,
        ).describe()
    )
    return {
        "model_id": model_id,
        "family": family,
        "definition": definition,
        "calibration_strategy": calibration.strategy_id,
        "target_scale": target.scale_id,
        "macro_mae": float(row["macro_mae"]),
        "macro_mean_pinball": float(row["macro_mean_pinball"]),
        "macro_spearman": float(row["macro_spearman"]),
        "macro_top_k_recall": float(row["macro_top_k_recall"]),
        "macro_coverage_p10_p90": float(row["macro_coverage_p10_p90"]),
        "macro_coverage_p25_p75": float(row["macro_coverage_p25_p75"]),
        "macro_mean_width_p10_p90": float(row["macro_mean_width_p10_p90"]),
        "macro_crossing_rate_raw": float(row["macro_crossing_rate_raw"]),
        "macro_crossing_rate_post": _macro(cells, "crossing_rate_post", model_id=model_id),
    }


def _study_checks(
    calibration_decision: Decision,
    horizon_decision: Decision,
    candidate_decision: Decision,
    *,
    selected: Mapping[str, Any],
    selected_evidence: CalibrationEvidence,
    cells: Sequence[Mapping[str, Any]],
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    for label, decision in (
        ("calibration", calibration_decision),
        ("horizon", horizon_decision),
        ("candidate", candidate_decision),
    ):
        check_id = f"phase4.{label}_rule"
        if decision.passed:
            checks.append(
                QualityCheck.ok(
                    check_id,
                    stage="phase4_distribution",
                    message=f"{decision.rule} selected {decision.selected}",
                    observed="; ".join(decision.reasons) or decision.selected,
                ),
            )
        else:
            checks.append(
                QualityCheck.fail(
                    check_id,
                    stage="phase4_distribution",
                    message=f"{decision.rule} could not select a production variant",
                    observed="; ".join(decision.failures),
                ),
            )

    # A diagnostic, deliberately not a gate. ``phase4_candidate_v1`` carries its own
    # coverage clauses and they are what decided the architecture; re-running the
    # *calibration* rule's bands over the winner afterwards would be tightening a frozen
    # rule after seeing its result. Measuring and publishing the same numbers is not.
    hard_requirements = CALIBRATION_ACCEPTANCE.hard_requirement_failures(
        selected_evidence,
    )
    if hard_requirements:
        checks.append(
            QualityCheck.fail(
                "phase4.selected_distribution_calibration_diagnostic",
                stage="phase4_distribution",
                message=(
                    "the promoted distribution is outside a calibration band the "
                    "phase4_calibration_v1 rule applies when choosing between calibration "
                    "variants; reported as a limitation, not applied as a gate"
                ),
                observed="; ".join(hard_requirements),
                severity=Severity.WARNING,
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "phase4.selected_distribution_calibration_diagnostic",
                stage="phase4_distribution",
                message="the promoted distribution sits inside every calibration band",
                observed=f"variant {selected_evidence.variant_id}",
            ),
        )

    post = float(selected["macro_crossing_rate_post"])
    if post > 0.0:
        checks.append(
            QualityCheck.fail(
                "phase4.production_quantiles_monotonic",
                stage="phase4_distribution",
                message="the selected distribution still produces crossing quantiles",
                observed=f"macro post-processing crossing rate {post:.6f}",
                expected="0",
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "phase4.production_quantiles_monotonic",
                stage="phase4_distribution",
                message="the selected distribution never produces crossing quantiles",
                observed=f"{len(cells)} evaluation cell(s), post-processing crossing rate 0",
            ),
        )
    return checks


# ---------------------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------------------


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for label, _ in columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [header, divider]
    for row in rows:
        cells: list[str] = []
        for _, key in columns:
            value = row.get(key)
            if isinstance(value, float):
                cells.append(f"{value:.4f}" if abs(value) < 1000 else f"{value:.1f}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _delta_lines(deltas: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for name, payload in sorted(deltas.items()):
        for metric, item in sorted(payload.items()):
            lines.append(
                f"- `{name}` **{metric}** {item['delta']:+.4f} "
                f"(95% CI {item['ci_low']:+.4f} to {item['ci_high']:+.4f}"
                f"{', excludes zero' if item['ci_excludes_zero'] else ', includes zero'})",
            )
    return lines


def to_json(
    result: DistributionStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    stamped = generated_at or utc_now()
    return {
        "study": DISTRIBUTION_STUDY_VERSION,
        "study_id": (
            f"{DISTRIBUTION_STUDY_VERSION}:{result.config.seed}:"
            f"{stamped.strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "generated_at_utc": isoformat_utc(stamped),
        "git_sha": git_sha or "unknown",
        "runtime_seconds": result.runtime_seconds,
        "configuration": result.config.to_dict(),
        "frozen_rules": all_rules(),
        "dataset": result.dataset,
        "feature_set": result.feature_selection,
        "folds": result.folds,
        "models": result.model_definitions,
        "metrics_by_cell": result.cells,
        "aggregates": result.aggregates,
        "aggregates_by_position": result.positional,
        "aggregates_by_season": result.seasonal,
        "aggregates_by_scoring": result.scoring,
        "paired_deltas": result.deltas,
        "calibration_decision": result.calibration_decision.to_dict(),
        "horizon_decision": result.horizon_decision.to_dict(),
        "candidate_decision": result.candidate_decision.to_dict(),
        "selected_architecture": result.selected,
        "fit_diagnostics": result.fit_diagnostics,
        "checks": [check.to_dict() for check in result.checks],
        "status": "pass" if result.passed else "fail",
    }


def to_markdown(
    result: DistributionStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    stamped = generated_at or utc_now()
    selected = result.selected
    lines: list[str] = [
        "# Phase 4, stage B — the production predictive distribution",
        "",
        (
            f"Study `{DISTRIBUTION_STUDY_VERSION}`, rules `{PHASE4_RULES_VERSION}`, seed "
            f"`{result.config.seed}`, code `{git_sha or 'unknown'}`, generated "
            f"{isoformat_utc(stamped)}."
        ),
        "",
        "## Conclusion",
        "",
        f"**`{selected['model_id']}` is the production predictive distribution.**",
        "",
        f"- family: {selected['family']}",
        f"- calibration: `{selected['calibration_strategy']}`",
        f"- target scale: `{selected['target_scale']}`",
        f"- macro MAE {selected['macro_mae']:.4f}",
        f"- macro mean pinball {selected['macro_mean_pinball']:.4f}",
        f"- macro Spearman {selected['macro_spearman']:.4f}",
        f"- macro top-K recall {selected['macro_top_k_recall']:.4f}",
        (
            f"- P10-P90 coverage {selected['macro_coverage_p10_p90']:.4f} at mean width "
            f"{selected['macro_mean_width_p10_p90']:.1f}"
        ),
        f"- P25-P75 coverage {selected['macro_coverage_p25_p75']:.4f}",
        (
            f"- quantile crossing: {selected['macro_crossing_rate_raw']:.4f} raw, "
            f"{selected['macro_crossing_rate_post']:.4f} after post-processing"
        ),
        "",
        "The three decisions, each taken by a rule frozen in ADR-030 before its evidence "
        "existed and applied in the declared order:",
        "",
    ]
    for label, decision in (
        ("Calibration", result.calibration_decision),
        ("Horizon sensitivity", result.horizon_decision),
        ("Candidate A vs B", result.candidate_decision),
    ):
        verdict = "decisive" if decision.decisive else "not decisive; the incumbent stands"
        lines.append(f"**{label}** (`{decision.rule}`) selected `{decision.selected}` — {verdict}.")
        lines.append("")
        for reason in decision.reasons:
            lines.append(f"> {reason}")
        for failure in decision.failures:
            lines.append(f"> **failed:** {failure}")
        lines.append("")

    lines.extend(
        [
            "## Aggregate performance",
            "",
            "Macro means over validation season x position x scoring cells, development "
            "folds 2020-2024, window "
            f"`{result.config.window}`.",
            "",
            _table(
                sorted(result.aggregates, key=lambda row: str(row["model_id"])),
                (
                    ("Model", "model_id"),
                    ("Cells", "cells"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Top-K", "macro_top_k_recall"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ("P25-P75 cov", "macro_coverage_p25_p75"),
                    ("P10-P90 width", "macro_mean_width_p10_p90"),
                    ("Raw crossing", "macro_crossing_rate_raw"),
                ),
            ),
            "",
            "Post-processing crossing rate by model:",
            "",
            _table(
                [
                    {
                        "model_id": model_id,
                        "crossing_rate_post": _macro(
                            result.cells,
                            "crossing_rate_post",
                            model_id=model_id,
                        ),
                    }
                    for model_id in sorted({str(cell["model_id"]) for cell in result.cells})
                ],
                (("Model", "model_id"), ("Post crossing", "crossing_rate_post")),
            ),
            "",
            "## Paired deltas",
            "",
        ],
    )
    lines.extend(_delta_lines(result.deltas))
    lines.extend(
        [
            "",
            (
                f"Paired block bootstrap, {result.config.bootstrap_replicates} replicates, "
                f"seed {result.config.seed}, resampling player-seasons within validation "
                "season x position x scoring blocks and carrying both variants' predictions "
                "for the same rows through the same resample."
            ),
            "",
            "## By position",
            "",
            _table(
                sorted(
                    result.positional,
                    key=lambda row: (str(row["position"]), str(row["model_id"])),
                ),
                (
                    ("Position", "position"),
                    ("Model", "model_id"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Top-K", "macro_top_k_recall"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ("P25-P75 cov", "macro_coverage_p25_p75"),
                ),
            ),
            "",
            "## By validation season",
            "",
            _table(
                sorted(
                    result.seasonal,
                    key=lambda row: (int(row["validation_season"]), str(row["model_id"])),
                ),
                (
                    ("Season", "validation_season"),
                    ("Model", "model_id"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                ),
            ),
            "",
            "## By scoring preset",
            "",
            _table(
                sorted(
                    result.scoring,
                    key=lambda row: (str(row["scoring_preset"]), str(row["model_id"])),
                ),
                (
                    ("Scoring", "scoring_preset"),
                    ("Model", "model_id"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Pinball", "macro_mean_pinball"),
                ),
            ),
            "",
            "## Checks",
            "",
        ],
    )
    for check in result.checks:
        mark = "ok" if check.status is CheckStatus.PASS else str(check.severity)
        lines.append(f"- [{mark}] `{check.check_id}` — {check.message}")
    lines.append("")
    lines.append(
        "Season 2025 is sealed and was not touched: the modelling frame drops it at load "
        "time, and every fold above validates a development season.",
    )
    lines.append("")
    return "\n".join(lines)


def write_distribution_report(
    result: DistributionStudyResult,
    out_dir: Path,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
    predictions_dir: Path | None = None,
) -> list[Path]:
    """Write both reports, plus the out-of-fold predictions stage C consumes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = generated_at or utc_now()
    written: list[Path] = []

    payload = to_json(result, git_sha=git_sha, generated_at=stamped)
    json_path = out_dir / "experiment.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(json_path)

    markdown_path = out_dir / "experiment.md"
    markdown_path.write_text(
        to_markdown(result, git_sha=git_sha, generated_at=stamped),
        encoding="utf-8",
    )
    written.append(markdown_path)

    if predictions_dir is not None and result.predictions is not None:
        predictions_dir.mkdir(parents=True, exist_ok=True)
        selected = str(result.selected["model_id"])
        frame = result.predictions.filter(pl.col("model_id") == selected)
        path = predictions_dir / OOF_PREDICTIONS_FILE
        frame.write_parquet(path, compression="zstd")
        written.append(path)
    return written
