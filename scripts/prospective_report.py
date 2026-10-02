"""Render a weekly-startsit-v2 prospective run as Markdown (``weekly-v2-prospective.yml``).

The same text is the run's step summary and, when a look was taken, the body of the issue
that tells the owner. It reads only the status and verdict files the evaluation command
wrote; it decides nothing.

    python scripts/prospective_report.py --status prospective/status.json \\
        [--verdict prospective/prospective_first.json] --out prospective/report.md
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

#: What each outcome means for the owner, at each look (MODELING 35.6, prospective_looks_v1).
NEXT_STEP: dict[tuple[str, str], str] = {
    ("first", "promote"): (
        "v2 beat v1 at the 99% interim boundary, so the evaluation is over and v2 may replace "
        "v1. Nothing switches by itself: promotion is a reviewed change (export this verdict "
        "with `ffdraft evaluate-weekly-v2-prospective --store market-data --export`, regenerate "
        "the model card, serve v2, keep v1 as the challenger)."
    ),
    ("first", "reject"): (
        "v2 is worse than v1 beyond doubt, so the evaluation is over. v1 stays; retire the "
        "v2 shadow."
    ),
    ("first", "insufficient_evidence"): (
        "Not decided yet, which is not a rejection. v1 stays, v2 keeps running in shadow, and "
        "the final look is taken automatically once the season's last week is complete."
    ),
    ("final", "promote"): (
        "v2 beat v1 at the final look, so v2 may replace v1. Nothing switches by itself: "
        "promotion is a reviewed change (export the verdict, regenerate the card, serve v2)."
    ),
    ("final", "reject"): "v2 is worse than v1. v1 stays; retire the v2 shadow.",
    ("final", "insufficient_evidence"): (
        "The season ended without a decision, which is not a rejection. v1 stays; the "
        "evaluation is closed."
    ),
}


def _number(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def render(status: dict[str, Any], verdict: dict[str, Any] | None) -> str:
    """The run as Markdown: progress always, and the verdict when a look was taken."""
    season = status.get("season")
    lines = [f"## weekly-startsit-v2 prospective holdout, {season}", ""]
    if status.get("closed") and not status.get("taken"):
        recorded = status.get("recorded_looks") or {}
        lines.append(
            "The evaluation is closed; nothing was counted or taken. Recorded looks: "
            + (", ".join(f"{look}: {outcome}" for look, outcome in recorded.items()) or "none")
            + ".",
        )
        return "\n".join(lines) + "\n"
    minimum = status.get("minimum") or {}
    lines += [
        "| | held | minimum |",
        "|---|---|---|",
        f"| weeks scored | {status.get('weeks', 0)} | {minimum.get('weeks', '—')} |",
        f"| scored rows | {status.get('rows', 0)} | {minimum.get('rows', '—')} |",
        f"| decision-pool pairs | {status.get('pairs', 0)} | {minimum.get('pairs', '—')} |",
        "",
        "Weeks whose outcomes have arrived: "
        + (", ".join(str(week) for week in status.get("complete_weeks") or []) or "none yet")
        + f". Shadow captures read: {status.get('captures', 0)}; pregame rows eligible: "
        f"{status.get('eligible', 0)}. A week is scored when both hold.",
        "",
    ]
    taken = status.get("taken")
    if not taken or verdict is None:
        due = status.get("due")
        lines.append(
            "No look was due."
            if due is None
            else f"The {due} look is due; this run did not take it (no --take-due-look).",
        )
        return "\n".join(lines) + "\n"
    outcome = str(verdict.get("outcome"))
    interval = verdict.get("interval") or {}
    summary = verdict.get("summary") or {}
    lines += [
        f"### The {taken} look: **{outcome.replace('_', ' ')}**",
        "",
        NEXT_STEP.get((str(taken), outcome), ""),
        "",
    ]
    if interval:
        lines += [
            f"Pinball difference (v1 − v2, positive favours v2): "
            f"{_number(interval.get('difference'), 5)}, "
            f"{round(100 * float(interval.get('level', 0)))}% week-clustered interval "
            f"[{_number(interval.get('lower'), 5)}, {_number(interval.get('upper'), 5)}] "
            f"over {interval.get('weeks')} weeks.",
            "",
            "| model | pinball | P10–P90 coverage | pair accuracy | pair Brier | pairs |",
            "|---|---|---|---|---|---|",
        ]
        for model in ("v1", "v2"):
            row = summary.get(model) or {}
            lines.append(
                f"| {model} | {_number(row.get('pinball'))} | {_number(row.get('coverage_80'), 3)} "
                f"| {_number(row.get('accuracy'))} | {_number(row.get('brier'))} "
                f"| {row.get('pairs', '—')} |",
            )
        lines.append("")
    lines.append(
        "The look is recorded in the retained store (`gameday/weekly_v2_look`) with the rows it "
        "judged, and is never taken again.",
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--verdict", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    status = json.loads(args.status.read_text(encoding="utf-8"))
    verdict = (
        json.loads(args.verdict.read_text(encoding="utf-8"))
        if args.verdict is not None and args.verdict.is_file()
        else None
    )
    args.out.write_text(render(status, verdict), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
