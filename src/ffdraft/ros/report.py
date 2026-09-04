"""Serialization of a rest-of-season experiment.

Two artifacts per run, and the same rule Release 1 follows: the JSON is the machine-readable
record every downstream check reads, and the Markdown is written for a human who has to
decide whether to believe the JSON. Neither is allowed to contain a number the run did not
measure.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ffdraft.ros.experiment import CANDIDATE_ID, RosExperimentResult
from ffdraft.ros.gate import ROS_PROMOTION_CRITERIA
from ffdraft.timeutil import isoformat_utc

__all__ = ["to_json", "to_markdown", "write_ros_report"]

#: The development comparison and the sealed evaluation are different documents and must
#: never overwrite each other: a run that consumed the holdout replacing the report that
#: justified the freeze would destroy the evidence that the freeze came first.
_FILE_STEMS: Mapping[str, str] = {
    "development": "experiment",
    "final_holdout": "final_holdout",
}


def to_json(result: RosExperimentResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    header = "| " + " | ".join(title for _, title in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(str(row.get(key, "")) for key, _ in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _number(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def to_markdown(result: RosExperimentResult) -> str:
    config = result.config
    lines: list[str] = [
        f"# Rest-of-season experiment — `{config.label}`",
        "",
        f"Generated {isoformat_utc(result.generated_at)} · "
        f"experiment `{config.to_dict()['experiment_version']}` · seed `{config.seed}`.",
        "",
        "## What was measured",
        "",
        f"- grain: `{result.dataset['grain']}`",
        f"- rows scored: **{result.predictions.height:,}**",
        f"- seasons: {result.dataset['seasons']}",
        f"- folds: {[fold['fold_id'] for fold in config.to_dict()['folds']]}",
        "- evaluation cell: `season x through_week x position x scoring_preset`",
        "",
        "## Macro results",
        "",
        "Macro means across evaluation cells, so one week's quarterback board weighs the "
        "same as one week's receiver board.",
        "",
    ]
    rows = [
        {
            "model": model_id,
            "mae": _number(values["mae"], 2),
            "pinball": _number(values["mean_pinball"]),
            "spearman": _number(values["spearman"]),
            "top_k": _number(values["top_k_recall"]),
            "cov_p10_p90": _number(values["coverage_p10_p90"]),
            "cov_p25_p75": _number(values["coverage_p25_p75"]),
            "width_p10_p90": _number(values["mean_width_p10_p90"], 1),
            "cells": int(values["cells"]),
        }
        for model_id, values in result.macro.items()
    ]
    lines.append(
        _table(
            rows,
            (
                ("model", "model"),
                ("mae", "MAE"),
                ("pinball", "pinball"),
                ("spearman", "Spearman"),
                ("top_k", "top-K recall"),
                ("cov_p10_p90", "P10-P90 coverage"),
                ("cov_p25_p75", "P25-P75 coverage"),
                ("width_p10_p90", "P10-P90 width"),
                ("cells", "cells"),
            ),
        ),
    )
    lines.extend(
        [
            "",
            f"**Primary baseline: `{result.primary_baseline}`** — chosen by the frozen rule "
            "(lowest development macro pinball loss), not by preference.",
            "",
            "## Paired deltas",
            "",
            f"`{CANDIDATE_ID}` minus `{result.primary_baseline}`, paired within cell, "
            f"{config.replicates} bootstrap replicates. Negative is better for a loss.",
            "",
        ],
    )
    delta_rows = [
        {
            "metric": metric,
            "baseline": _number(delta.baseline),
            "candidate": _number(delta.candidate),
            "delta": _number(delta.delta, 4),
            "ci": f"[{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]",
            "resolved": "yes" if delta.significant else "no",
        }
        for metric, delta in result.deltas.items()
    ]
    lines.append(
        _table(
            delta_rows,
            (
                ("metric", "metric"),
                ("baseline", "baseline"),
                ("candidate", "candidate"),
                ("delta", "delta"),
                ("ci", "95% CI"),
                ("resolved", "interval excludes 0"),
            ),
        ),
    )

    lines.extend(["", "## Predeclared cohorts", "", _cohort_table(result), ""])
    lines.extend(["## By snapshot week", "", _week_table(result), ""])
    lines.extend(["## Promotion gate", "", *_gate_lines(result), ""])
    lines.extend(["## Checks", ""])
    lines.extend(
        f"- `{check.check_id}` **{check.status}** — {check.message} ({check.observed})"
        for check in result.checks
    )
    return "\n".join(lines) + "\n"


def _cohort_table(result: RosExperimentResult) -> str:
    rows = [
        {
            "slice": f"`{item.slice_id}` / {item.label}",
            "rows": f"{item.rows:,}",
            "decisive": "yes" if item.decisive else "no",
            "base_mae": _number(item.baseline_mae, 2),
            "cand_mae": _number(item.candidate_mae, 2),
            "base_rho": _number(item.baseline_spearman),
            "cand_rho": _number(item.candidate_spearman),
            "coverage": _number(item.candidate_coverage),
        }
        for item in result.cohorts
    ]
    return _table(
        rows,
        (
            ("slice", "cohort"),
            ("rows", "rows"),
            ("decisive", "decisive"),
            ("base_mae", "baseline MAE"),
            ("cand_mae", "candidate MAE"),
            ("base_rho", "baseline Spearman"),
            ("cand_rho", "candidate Spearman"),
            ("coverage", "candidate P10-P90 coverage"),
        ),
    )


def _week_table(result: RosExperimentResult) -> str:
    aggregated = result.cells_by_week()
    weeks = sorted({int(row["through_week"]) for row in aggregated})
    rows: list[dict[str, Any]] = []
    for week in weeks:
        row: dict[str, Any] = {"week": week}
        for model_id in result.macro:
            match = [
                item
                for item in aggregated
                if item["model_id"] == model_id and int(item["through_week"]) == week
            ]
            row[model_id] = _number(match[0]["mae"], 2) if match else "—"
        rows.append(row)
    columns = [("week", "through week"), *[(model, model) for model in result.macro]]
    return _table(rows, columns) + "\n\nMAE, macro-averaged across the cells of that week."


def _gate_lines(result: RosExperimentResult) -> list[str]:
    verdict = "**PROMOTED**" if result.gate.promoted else "**NOT PROMOTED**"
    lines = [
        f"Rule `{ROS_PROMOTION_CRITERIA.version}`, frozen before the comparison ran.",
        "",
        f"{verdict} — `{result.gate.candidate}` against `{result.gate.primary_baseline}`.",
        "",
    ]
    if result.gate.satisfied:
        lines.append("Satisfied:")
        lines.extend(f"- {reason}" for reason in result.gate.satisfied)
        lines.append("")
    if result.gate.reasons:
        lines.append("Failed:")
        lines.extend(f"- {reason}" for reason in result.gate.reasons)
        lines.append("")
    return lines


def write_ros_report(
    result: RosExperimentResult,
    out_dir: Path,
    *,
    cells_dir: Path | None = None,
) -> list[Path]:
    """Write both artifacts and return the paths.

    ``cells_dir`` receives the full per-cell metric table. It is deliberately not the report
    directory: there are several thousand cells, and a committed report has to stay
    reviewable. The report carries the week-by-week and season-by-position aggregates a
    reader actually reads.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _FILE_STEMS.get(result.config.label, result.config.label)
    written: list[Path] = []
    for name, text in ((f"{stem}.json", to_json(result)), (f"{stem}.md", to_markdown(result))):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    if cells_dir is not None:
        cells_dir.mkdir(parents=True, exist_ok=True)
        path = cells_dir / f"ros_cells_{stem}.parquet"
        result.cell_frame().write_parquet(path, compression="zstd")
        written.append(path)
    return written
