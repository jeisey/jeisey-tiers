"""Serialization of the rest-of-season value study."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ffdraft.modeling.rules import CONVERGENCE_TOLERANCE, TIER_SELECTION, TIER_STABILITY_GATE
from ffdraft.ros.study import RosValueStudyResult
from ffdraft.ros.value import REPLACEMENT_SELECTION, RosReplacementRule
from ffdraft.timeutil import isoformat_utc

__all__ = ["to_json", "to_markdown", "write_ros_value_report"]

_JSON_FILE = "value_study.json"
_MARKDOWN_FILE = "value_study.md"


def to_json(result: RosValueStudyResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True, default=str) + "\n"


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


def to_markdown(result: RosValueStudyResult) -> str:
    config = result.config
    lines: list[str] = [
        "# Rest-of-season value study",
        "",
        f"Generated {isoformat_utc(result.generated_at)} · fold `{config.fold.fold_id}` · "
        f"seed `{config.seed}` · reference draws `{config.draws}`.",
        "",
        "## 1. Which replacement?",
        "",
        "Both interpretations are run over identical simulated seasons. "
        f"Rule `{REPLACEMENT_SELECTION.version}` decides.",
        "",
    ]
    for rule in RosReplacementRule:
        lines.append(f"- **`{rule}`** — {rule.description}")
    lines.extend(["", _sensitivity_table(result), ""])
    lines.extend(_decision_lines("Decision", result.replacement_decision))

    lines.extend(
        [
            "## 2. How many draws?",
            "",
            f"Frozen tolerance `{CONVERGENCE_TOLERANCE.version}`, ladder "
            f"{list(CONVERGENCE_TOLERANCE.draw_ladder)}. Two comparisons must both pass at a "
            "candidate count: against the reference count at one seed, and between two seeds "
            "at that count.",
            "",
            _convergence_table(result),
            "",
        ],
    )
    lines.extend(_decision_lines("Decision", result.convergence_decision))

    lines.extend(
        [
            "## 3. Are the tiers real?",
            "",
            f"Penalty selection `{TIER_SELECTION.version}` over the frozen grid "
            f"{list(TIER_SELECTION.penalties)}; stability gate `{TIER_STABILITY_GATE.version}`.",
            "",
            _tier_table(result),
            "",
        ],
    )
    lines.extend(_decision_lines("Penalty", result.tier_decision))
    lines.extend(_decision_lines("Stability", result.stability_decision))

    lines.extend(["## Checks", ""])
    lines.extend(
        f"- `{check.check_id}` **{check.status}** — {check.message} ({check.observed})"
        for check in result.checks
    )
    return "\n".join(lines) + "\n"


def _sensitivity_table(result: RosValueStudyResult) -> str:
    rows = [
        {
            "scenario": f"{row['scoring_preset']} w{int(row['through_week']):02d}",
            "spearman": _number(row["fair_rank_spearman"], 4),
            "rank_change": _number(row["mean_abs_rank_change_top_150"], 2),
            "max_change": _number(row["max_abs_rank_change"], 0),
            "overlap": _number(row["top_50_overlap"]),
            "shared": row["shared_players"],
        }
        for row in result.replacement_sensitivity
    ]
    return _table(
        rows,
        (
            ("scenario", "scenario"),
            ("spearman", "fair-rank Spearman"),
            ("rank_change", "mean |Δrank| top 150"),
            ("max_change", "max |Δrank|"),
            ("overlap", "top-50 overlap"),
            ("shared", "players"),
        ),
    )


def _convergence_table(result: RosValueStudyResult) -> str:
    rows = [
        {
            "scenario": item.scenario,
            "comparison": item.comparison,
            "draws": item.draws,
            "expected": _number(item.mean_abs_expected_vorp),
            "p50": _number(item.mean_abs_p50_vorp),
            "rank": _number(item.mean_abs_rank_change_top_150, 2),
            "spearman": _number(item.fair_rank_spearman, 4),
            "ari": _number(item.tier_adjusted_rand),
        }
        for item in result.convergence_evidence
    ]
    return _table(
        rows,
        (
            ("scenario", "scenario"),
            ("comparison", "comparison"),
            ("draws", "draws"),
            ("expected", "mean |Δ E[VORP]|"),
            ("p50", "mean |Δ P50 VORP|"),
            ("rank", "mean |Δrank| top 150"),
            ("spearman", "fair-rank Spearman"),
            ("ari", "tier ARI"),
        ),
    )


def _tier_table(result: RosValueStudyResult) -> str:
    penalties = sorted({float(row["penalty"]) for row in result.tier_shape})
    rows: list[dict[str, Any]] = []
    for penalty in penalties:
        for algorithm in sorted({str(row["algorithm"]) for row in result.tier_shape}):
            subset = [
                row
                for row in result.tier_shape
                if float(row["penalty"]) == penalty and row["algorithm"] == algorithm
            ]
            if not subset:
                continue
            rows.append(
                {
                    "algorithm": algorithm,
                    "penalty": penalty,
                    "tiers": _number(
                        sum(int(row["tier_count"]) for row in subset) / len(subset),
                        1,
                    ),
                    "singleton": _number(
                        sum(float(row["singleton_rate"]) for row in subset) / len(subset),
                    ),
                    "largest": _number(
                        sum(float(row["largest_tier_share"]) for row in subset) / len(subset),
                    ),
                    "scenarios": len(subset),
                },
            )
    return _table(
        rows,
        (
            ("algorithm", "algorithm"),
            ("penalty", "penalty"),
            ("tiers", "mean tiers"),
            ("singleton", "singleton rate"),
            ("largest", "largest tier share"),
            ("scenarios", "scenarios"),
        ),
    )


def _decision_lines(title: str, decision: Any) -> list[str]:
    lines = [
        f"**{title}: `{decision.selected}`** (rule `{decision.rule}`, "
        f"decisive={decision.decisive})",
        "",
    ]
    lines.extend(f"- {reason}" for reason in decision.reasons)
    lines.extend(f"- **failed:** {failure}" for failure in decision.failures)
    lines.append("")
    return lines


def write_ros_value_report(result: RosValueStudyResult, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in ((_JSON_FILE, to_json(result)), (_MARKDOWN_FILE, to_markdown(result))):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
