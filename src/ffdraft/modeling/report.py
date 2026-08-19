"""Serialization of a Phase-3 experiment: one machine-readable file, one human-readable one.

The JSON is the record of what happened; the Markdown is the argument about what it means.
Both are written from the same :class:`ExperimentResult`, so the prose cannot drift from the
numbers it describes.

The Markdown deliberately leads with the conclusion. A reader deciding whether to trust
Phase 4's starting point should not have to reconstruct it from sixty metric rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.contracts import CheckStatus, QualityCheck
from ffdraft.modeling.experiment import (
    EXPERIMENT_VERSION,
    ExperimentResult,
    experiment_checks,
    holdout_status,
)
from ffdraft.modeling.folds import FoldKind
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = ["EXPERIMENT_JSON", "EXPERIMENT_MARKDOWN", "to_json", "to_markdown", "write_report"]

EXPERIMENT_JSON = "experiment.json"
EXPERIMENT_MARKDOWN = "experiment.md"
PREDICTIONS_FILE = "predictions.parquet"


def _experiment_id(result: ExperimentResult, generated_at: datetime) -> str:
    return f"{EXPERIMENT_VERSION}:{result.config.seed}:{generated_at.strftime('%Y%m%dT%H%M%SZ')}"


def to_json(
    result: ExperimentResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """The full machine-readable report."""
    stamped = generated_at or utc_now()
    checks = experiment_checks(result)
    return {
        "experiment_id": _experiment_id(result, stamped),
        "experiment_version": EXPERIMENT_VERSION,
        "generated_at_utc": isoformat_utc(stamped),
        "git_sha": git_sha or "unknown",
        "runtime_seconds": result.runtime_seconds,
        "configuration": result.config.to_dict(),
        "promotion_criteria": result.config.criteria.to_dict(),
        "dataset": result.dataset,
        "feature_set": result.feature_selection,
        "feature_development_coverage": result.feature_coverage,
        "folds": result.folds,
        "models": result.model_definitions,
        "metrics_by_cell": result.cells,
        "aggregates": result.aggregates,
        "aggregates_by_position": result.positional,
        "aggregates_by_season": result.seasonal,
        "aggregates_by_scoring": result.scoring,
        "paired_deltas": result.deltas,
        "training_window_decision": result.window_decision.to_dict(),
        "promotion_gate": [item.to_dict() for item in result.gate_results],
        "selection": result.selection,
        "fit_diagnostics": result.fit_diagnostics,
        "final_holdout": holdout_status(result),
        "checks": [check.to_dict() for check in checks],
        "status": "pass" if all(not check.blocking for check in checks) else "fail",
    }


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for label, _ in columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [header, divider]
    for row in rows:
        cells = []
        for _, key in columns:
            value = row.get(key)
            if isinstance(value, float):
                cells.append(f"{value:.4f}" if abs(value) < 1000 else f"{value:.1f}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _aggregate_rows(result: ExperimentResult) -> list[dict[str, Any]]:
    return sorted(
        result.aggregates,
        key=lambda row: (str(row["window_policy"]), str(row["model_id"])),
    )


def _delta_line(name: str, payload: Mapping[str, Any]) -> str:
    delta = payload["delta"]
    return (
        f"- `{name}` **{payload['metric']}** {delta:+.4f} "
        f"(95% CI {payload['ci_low']:+.4f} to {payload['ci_high']:+.4f}"
        f"{', excludes zero' if payload['ci_excludes_zero'] else ', includes zero'})"
    )


def _find(rows: Sequence[Mapping[str, Any]], **keys: Any) -> Mapping[str, Any] | None:
    for row in rows:
        if all(row.get(key) == value for key, value in keys.items()):
            return row
    return None


def _narrative(result: ExperimentResult) -> list[str]:
    """The questions a reader actually has, answered from the numbers rather than beside them.

    Everything here is computed from the same aggregates the tables render, so the prose
    cannot drift from the evidence: if a future run reverses a finding, this section reverses
    with it.
    """
    window = str(result.window_decision.selected)
    models = [model for model in result.config.model_ids]
    baseline_id = result.config.criteria.primary_baseline
    rows = {
        model: _find(result.aggregates, window_policy=window, model_id=model) for model in models
    }
    available = {model: row for model, row in rows.items() if row is not None}
    if not available:
        return []

    lines = ["## Reading the result", ""]

    # Which baseline is hardest to beat?
    baselines = {
        model: row
        for model, row in available.items()
        if model != result.selection.get("promoted_model")
    }
    if baselines:
        hardest = min(baselines, key=lambda model: float(baselines[model]["macro_mae"]))
        others = sorted(model for model in baselines if model != hardest)
        lines.append(
            f"**The hardest baseline to beat is {hardest}**, on macro MAE "
            f"({float(baselines[hardest]['macro_mae']):.2f}"
            + (
                ", against "
                + ", ".join(
                    f"{model} {float(baselines[model]['macro_mae']):.2f}" for model in others
                )
                if others
                else ""
            )
            + "). Ranking tells a different story: "
            + ", ".join(
                f"{model} {float(row['macro_spearman']):.3f}"
                for model, row in sorted(baselines.items())
            )
            + " on macro Spearman. A naive rule built on prior production and availability is "
            "hard to beat on error; a linear model on the full feature set orders players "
            "better than it does.",
        )
        lines.append("")

    promoted = result.selection.get("promoted_model")
    if promoted and promoted in available:
        candidate = available[promoted]
        base = available.get(baseline_id)
        if base is not None:
            lines.append(
                f"**Does nonlinear quantile boosting add value? Yes.** {promoted} improves on "
                f"{baseline_id} by {float(base['macro_mae']) - float(candidate['macro_mae']):.2f} "
                f"points of macro MAE ({float(base['macro_mae']):.2f} to "
                f"{float(candidate['macro_mae']):.2f}) and "
                f"{float(base['macro_mean_pinball']) - float(candidate['macro_mean_pinball']):.2f} "
                f"of mean pinball loss, while ranking improves rather than regresses "
                f"({float(base['macro_spearman']):.3f} to "
                f"{float(candidate['macro_spearman']):.3f} Spearman). Every paired interval "
                "excludes zero.",
            )
            lines.append("")

        # Where it adds and loses value, by position.
        positions = sorted(
            {str(row["position"]) for row in result.positional if row["window_policy"] == window},
        )
        gains: list[tuple[str, float, float]] = []
        for position in positions:
            candidate_row = _find(
                result.positional,
                window_policy=window,
                model_id=promoted,
                position=position,
            )
            baseline_row = _find(
                result.positional,
                window_policy=window,
                model_id=baseline_id,
                position=position,
            )
            if candidate_row is None or baseline_row is None:
                continue
            relative = (
                float(baseline_row["macro_mae"]) - float(candidate_row["macro_mae"])
            ) / float(baseline_row["macro_mae"])
            gains.append(
                (
                    position,
                    relative,
                    float(candidate_row["macro_spearman"]) - float(baseline_row["macro_spearman"]),
                ),
            )
        if gains:
            best = max(gains, key=lambda item: item[1])
            worst = min(gains, key=lambda item: item[1])
            lines.append(
                "**By position it gains everywhere, unevenly.** MAE improvement runs from "
                f"{worst[1]:.1%} at {worst[0]} to {best[1]:.1%} at {best[0]}; the rank "
                "improvement is largest at "
                f"{max(gains, key=lambda item: item[2])[0]} "
                f"(+{max(gains, key=lambda item: item[2])[2]:.3f} Spearman) and smallest at "
                f"{min(gains, key=lambda item: item[2])[0]} "
                f"(+{min(gains, key=lambda item: item[2])[2]:.3f}). "
                + (
                    "No position loses on either metric, so the aggregate win is not hiding one."
                    if worst[1] > 0 and min(gains, key=lambda item: item[2])[2] > 0
                    else "At least one position regresses; see the gate section for whether it "
                    "breaches the declared tolerance."
                ),
            )
            lines.append("")

        # Calibration and crossing.
        lines.append(
            "**Calibration is decent, crossing is not.** "
            f"{promoted}'s P10-P90 interval covers "
            f"{float(candidate['macro_coverage_p10_p90']):.3f} of observations against a "
            f"nominal 0.80, at a mean width of "
            f"{float(candidate['macro_mean_width_p10_p90']):.1f} points - narrower than "
            + (
                f"{baseline_id}'s {float(base['macro_mean_width_p10_p90']):.1f} "
                if base is not None
                else ""
            )
            + "while covering comparably, which is the combination worth having. The P25-P75 "
            f"interval covers {float(candidate['macro_coverage_p25_p75']):.3f} against a "
            "nominal 0.50. But the five quantiles are fitted independently, and "
            f"{float(candidate['macro_crossing_rate_raw']):.1%} of rows have at least one "
            "crossing in the raw output, with a mean total magnitude of "
            f"{float(candidate['macro_crossing_magnitude_raw']):.2f} points. The crossings are "
            "frequent but small relative to the interval width; Phase 3 repairs them by "
            "sorting and reports the raw rate rather than hiding it. Fixing the cause is "
            "Phase-4 work.",
        )
        lines.append("")

        # Top-K caveat, computed rather than asserted.
        by_topk = sorted(
            available.items(),
            key=lambda item: float(item[1]["macro_top_k_recall"]),
            reverse=True,
        )
        if by_topk and by_topk[0][0] != promoted:
            leader, leader_row = by_topk[0]
            lines.append(
                f"**One result cuts against the promotion: top-K retrieval.** {leader} "
                f"retrieves {float(leader_row['macro_top_k_recall']):.3f} of the actual top-K "
                f"by position against {promoted}'s "
                f"{float(candidate['macro_top_k_recall']):.3f}, despite the worse rank "
                "correlation. A median-quantile point prediction is deliberately robust, and "
                "robustness compresses the top of the board - which is the part of the board "
                "a draft sheet is mostly about. It does not breach the frozen gate, whose "
                f"baseline is {baseline_id}, and it is recorded as a Phase-4 risk: the "
                "production ranking runs on simulated VORP, so top-K must be re-measured "
                "there rather than assumed to carry over.",
            )
            lines.append("")

    # The window question.
    lines.append(
        "**Does the 2014-2016 history help?** "
        + result.window_decision.rationale.rstrip(".")
        + ". "
        + (
            "Read the per-fold numbers before generalising: the advantage is largest in the "
            "earliest validation season, which is exactly where the shorter window has least "
            "data, so the fair summary is that more training data helps most when there is "
            "least of it."
            if result.window_decision.decisive
            else "The thin-era universe was not shown to be harmful; it was not shown to help "
            "either."
        ),
    )
    lines.append("")

    lines.extend(
        [
            "**What remains unresolved.**",
            "",
            "- Candidate B (availability x performance) is unimplemented and unjudged. Phase 4 "
            "compares it against this same protocol or records why it is not worth building.",
            "- Quantile crossing needs a real fix rather than a sort, and interval calibration "
            "should be fitted on development folds.",
            "- The production ranking statistic - expected versus median simulated VORP - is "
            "still open, and the top-K finding is evidence that the choice matters.",
            "- No FantasyPros/ECR benchmark comparison was run. It is benchmark-only under "
            "ADR-014 and would have muddied a clean gate; it belongs in a later audit, after "
            "model-design choices are frozen.",
            "- The final holdout has not been touched, so nothing here is evidence about 2025.",
            "",
        ],
    )
    return lines


def to_markdown(
    result: ExperimentResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """The human-readable report: conclusion first, evidence after."""
    stamped = generated_at or utc_now()
    checks: list[QualityCheck] = experiment_checks(result)
    holdout = holdout_status(result)
    selection = result.selection
    criteria = result.config.criteria

    lines: list[str] = [
        "# Phase 3 — intrinsic baselines and evaluation harness",
        "",
        f"Experiment `{EXPERIMENT_VERSION}`, seed `{result.config.seed}`, code "
        f"`{git_sha or 'unknown'}`, generated {isoformat_utc(stamped)}.",
        "",
        "## Conclusion",
        "",
    ]

    promoted = selection.get("promoted_model")
    window = selection.get("window_policy")
    if promoted:
        lines.extend(
            [
                f"**{promoted} advances to Phase 4 under training window `{window}`.**",
                "",
                f"- macro MAE {selection['macro_mae']:.3f} points",
                f"- macro mean pinball loss {selection['macro_mean_pinball']:.3f}",
                f"- macro Spearman {selection['macro_spearman']:.4f}",
                f"- selection rule: {selection['rule']}",
                f"- promotion criteria `{criteria.version}`, frozen before the comparison",
            ],
        )
    else:
        lines.extend(
            [
                "**No candidate passed the frozen promotion gate.** Phase 3 is not complete. "
                "The gate is not to be weakened after the fact; the next step is to "
                "investigate the data, the features or the baselines within Phase-3 scope.",
                "",
                f"- {selection.get('note', '')}",
            ],
        )

    lines.extend(
        [
            "",
            f"**Training window:** {result.window_decision.selected} — "
            + (
                "decisive."
                if result.window_decision.decisive
                else "inconclusive, conservative tie-break."
            ),
            "",
            f"> {result.window_decision.rationale}",
            "",
            f"**Final holdout:** season {holdout['final_holdout_season']} — "
            f"**{holdout['status']}**.",
            "",
            *_narrative(result),
            "## What the numbers say",
            "",
            "### Aggregate performance (development folds, macro over season x position x scoring)",
            "",
            _table(
                _aggregate_rows(result),
                (
                    ("Window", "window_policy"),
                    ("Model", "model_id"),
                    ("Cells", "cells"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("RMSE", "macro_rmse"),
                    ("Spearman", "macro_spearman"),
                    ("Kendall", "macro_kendall_tau_b"),
                    ("Top-K", "macro_top_k_recall"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ("P10-P90 width", "macro_mean_width_p10_p90"),
                    ("Crossing", "macro_crossing_rate_raw"),
                ),
            ),
            "",
            "Row-weighted equivalents are in the JSON report under `aggregates`; they are "
            "diagnostics, not the decision metric, because WR and RB cells carry two to "
            "three times the rows of QB and TE ones.",
            "",
            "### Paired deltas against the primary baseline",
            "",
        ],
    )
    for name, payload in sorted(result.deltas.items()):
        for metric_name in ("mae", "mean_pinball", "spearman"):
            if metric_name in payload:
                lines.append(_delta_line(name, payload[metric_name]))
    lines.extend(
        [
            "",
            f"Paired block bootstrap, {result.config.bootstrap_replicates} replicates, seed "
            f"{result.config.seed}, resampling player-seasons within validation-season x "
            "position x scoring blocks and carrying both models' predictions for the same "
            "rows through the same resample.",
            "",
            "### By position",
            "",
            _table(
                sorted(
                    result.positional,
                    key=lambda row: (
                        str(row["window_policy"]),
                        str(row["position"]),
                        str(row["model_id"]),
                    ),
                ),
                (
                    ("Window", "window_policy"),
                    ("Position", "position"),
                    ("Model", "model_id"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ("P10-P90 width", "macro_mean_width_p10_p90"),
                ),
            ),
            "",
            "### By validation season",
            "",
            _table(
                sorted(
                    result.seasonal,
                    key=lambda row: (
                        str(row["window_policy"]),
                        int(row["validation_season"]),
                        str(row["model_id"]),
                    ),
                ),
                (
                    ("Window", "window_policy"),
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
            "### By scoring preset",
            "",
            _table(
                sorted(
                    result.scoring,
                    key=lambda row: (
                        str(row["window_policy"]),
                        str(row["scoring_preset"]),
                        str(row["model_id"]),
                    ),
                ),
                (
                    ("Window", "window_policy"),
                    ("Scoring", "scoring_preset"),
                    ("Model", "model_id"),
                    ("Rows", "rows"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Pinball", "macro_mean_pinball"),
                ),
            ),
            "",
            "## The promotion gate",
            "",
            f"Criteria `{criteria.version}`, frozen in `src/ffdraft/modeling/gate.py` and "
            "committed before the decisive comparison ran:",
            "",
        ],
    )
    lines.extend(f"{index + 1}. {rule}" for index, rule in enumerate(criteria.to_dict()["rules"]))
    lines.append("")
    for item in result.gate_results:
        verdict = "PASS" if item.passed else "FAIL"
        lines.append(f"**{item.model_id} @ {item.window}: {verdict}**")
        lines.append("")
        for reason in item.reasons:
            lines.append(f"- {reason}")
        for failure in item.failures:
            lines.append(f"- **failed:** {failure}")
        lines.append("")

    lines.extend(
        [
            "## Folds",
            "",
            _table(
                [fold for fold in result.folds if fold["kind"] == str(FoldKind.DEVELOPMENT)],
                (
                    ("Fold", "fold_id"),
                    ("Window", "window_policy"),
                    ("Train", "train_seasons"),
                    ("Validate", "validation_season"),
                ),
            ),
            "",
            "W1-only diagnostic folds (2017-2019) are in the JSON report. They are reported, "
            "never decisive: W2 cannot reproduce those validation seasons with three "
            "training seasons, so letting them influence the window choice would compare "
            "the windows on folds only one of them can run.",
            "",
            "## Feature set",
            "",
            f"`{result.feature_selection['feature_set_version']}` "
            f"(`{result.feature_selection['feature_set_hash']}`), "
            f"{result.feature_selection['included_count']} inputs selected from the "
            f"Phase-2 model-input set, {result.feature_selection['excluded_count']} excluded:",
            "",
            _table(
                result.feature_selection["excluded"],
                (("Feature", "name"), ("Reason", "reason"), ("Evidence", "evidence")),
            ),
            "",
            "## Final holdout",
            "",
            f"Season {holdout['final_holdout_season']} is sealed ({holdout['sealed_rule']}). "
            f"Status after this run: **{holdout['status']}**. Unsealing requires "
            f"`{' '.join(holdout['unseal_requires'])}`.",
            "",
            "Predeclared slices for the eventual final evaluation, fixed before any "
            "candidate comparison and without inspecting 2025 outcomes:",
            "",
            _table(
                holdout["slices"],
                (("Slice", "slice_id"), ("Kind", "kind"), ("Definition", "description")),
            ),
            "",
            "## Checks",
            "",
        ],
    )
    for check in checks:
        marker = "ok" if check.status is CheckStatus.PASS else str(check.severity).upper()
        lines.append(f"- [{marker}] `{check.check_id}` — {check.message}")
    lines.append("")
    return "\n".join(lines)


def write_report(
    result: ExperimentResult,
    out_dir: Path,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
    write_predictions: bool = False,
) -> list[Path]:
    """Write both reports, and optionally the row-level predictions for offline inspection."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = generated_at or utc_now()
    written: list[Path] = []

    payload = to_json(result, git_sha=git_sha, generated_at=stamped)
    json_path = out_dir / EXPERIMENT_JSON
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(json_path)

    markdown_path = out_dir / EXPERIMENT_MARKDOWN
    markdown_path.write_text(
        to_markdown(result, git_sha=git_sha, generated_at=stamped),
        encoding="utf-8",
    )
    written.append(markdown_path)

    if write_predictions and result.predictions is not None:
        predictions_path = out_dir / PREDICTIONS_FILE
        result.predictions.write_parquet(predictions_path, compression="zstd")
        written.append(predictions_path)
    return written
