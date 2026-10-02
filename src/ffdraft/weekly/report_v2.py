"""The v2 development report: every family's measured value over v1, and the frozen verdict.

Floats are rounded to ten decimals before writing, so two runs of the same code on the same
rows write the same bytes: Polars' parallel mean can move a summary in its sixteenth
significant digit (measured on v1's own report, 2026-10-01), and a report that changes in a
digit nobody reads is still a report that cannot be diffed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ffdraft.timeutil import isoformat_utc, utc_now
from ffdraft.weekly.frozen_v2 import V2_FAMILY_LABELS

__all__ = ["write_v2_report"]


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 10)
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(item) for item in value]
    return value


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def _markdown(report: Mapping[str, Any]) -> str:
    pooled = report["pooled"]
    lines = [
        "# weekly-startsit-v2 — development evaluation",
        "",
        f"Outcome: **{report['outcome']}**; v2 families: "
        f"**{', '.join(report['v2_families']) or 'none'}**.",
        "",
        "Rules frozen before this run (`src/ffdraft/weekly/frozen_v2.py`): "
        f"{report['rules']['family_selection']['version']}, "
        f"{report['rules']['promotion']['version']}. Folds: "
        f"{', '.join(str(season) for season in report['folds'])}.",
        "",
        "## Pooled, development folds",
        "",
        "| model | pinball | pinball (rows) | MAE (median) | pair accuracy | pair Brier "
        "| P10–P90 |",
        "|---|---|---|---|---|---|---|",
    ]
    for model, values in pooled.items():
        lines.append(
            f"| {model} | {_fmt(values['pinball'])} | {_fmt(values['pinball_rows'])} | "
            f"{_fmt(values['mae_median'], 3)} | {_fmt(values['pair_accuracy'])} | "
            f"{_fmt(values['pair_brier'])} | {_fmt(values['coverage_80'], 3)} |",
        )
    lines += [
        "",
        "## Each family's incremental value over v1 (weekly_family_selection_v1)",
        "",
        "| family | Δ pinball (v1 − v1+f) | 95% interval (week-clustered) | fold wins "
        "| Δ accuracy | Δ Brier | selected |",
        "|---|---|---|---|---|---|---|",
    ]
    for family, result in report["selection"]["families"].items():
        clauses = result["clauses"]
        interval = clauses["pinball_interval_above_zero"]
        decision = clauses["decision_not_worse"]
        lines.append(
            f"| {V2_FAMILY_LABELS.get(family, family)} | "
            f"{_fmt(clauses['pinball_below_v1']['difference'], 5)} | "
            f"[{_fmt(interval['lower'], 5)}, {_fmt(interval['upper'], 5)}] | "
            f"{clauses['pinball_fold_wins']['wins']}/{clauses['pinball_fold_wins']['folds']} | "
            f"{_fmt(decision['accuracy'] - decision['accuracy_v1'], 5)} | "
            f"{_fmt(decision['brier'] - decision['brier_v1'], 5)} | "
            f"{'yes' if result['passed'] else 'no'} |",
        )
    models = list(pooled)
    lines += [
        "",
        "## Macro pinball by season (each fold trained on the seasons before it)",
        "",
        "| season | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]
    for season, values in sorted(report["by_season"].items()):
        lines.append(
            f"| {season} | "
            + " | ".join(_fmt((values.get(model) or {}).get("pinball")) for model in models)
            + " |",
        )
    lines += [
        "",
        "## Macro pinball by position (pooled folds)",
        "",
        "| position | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]
    for position, values in report["by_position"].items():
        lines.append(
            f"| {position} | "
            + " | ".join(_fmt((values.get(model) or {}).get("pinball")) for model in models)
            + " |",
        )
    lines += [
        "",
        "## Where each family has something to say (diagnostic; decides nothing)",
        "",
        "| family | rows | share | v1 pinball | v1+family pinball |",
        "|---|---|---|---|---|",
    ]
    for family, entry in report["active_subsets"].items():
        lines.append(
            f"| {family} | {entry['rows']} | {_fmt(entry['share'], 3)} | "
            f"{_fmt(entry.get('v1'))} | {_fmt(entry.get(f'v1+{family}'))} |",
        )
    examined = report.get("previously_examined")
    if examined:
        lines += [
            "",
            f"## {examined['season']} (previously examined; decides nothing)",
            "",
            "| model | pinball | pair accuracy | pair Brier | P10–P90 |",
            "|---|---|---|---|---|",
        ]
        for model, values in examined["summary"].items():
            lines.append(
                f"| {model} | {_fmt(values['pinball'])} | {_fmt(values['pair_accuracy'])} | "
                f"{_fmt(values['pair_brier'])} | {_fmt(values['coverage_80'], 3)} |",
            )
        lines.append("")
        lines.append(f"Consistent with development: **{examined['consistent']}**.")
    verdict = report.get("development_verdict")
    if verdict:
        lines += ["", "## weekly_promotion_v1 development clauses, asked of v2", ""]
        for clause, detail in verdict["clauses"].items():
            lines.append(f"- `{clause}`: {'pass' if detail['passed'] else 'FAIL'}")
    lines.append("")
    return "\n".join(lines)


def write_v2_report(result: Mapping[str, Any], out_dir: Path) -> list[Path]:
    report = _rounded({key: value for key, value in result.items() if not key.startswith("_")})
    report["generated_at_utc"] = isoformat_utc(utc_now())
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "experiment.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = out_dir / "experiment.md"
    md_path.write_text(_markdown(report), encoding="utf-8")
    return [json_path, md_path]
