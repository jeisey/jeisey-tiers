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
