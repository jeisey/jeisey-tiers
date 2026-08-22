"""Decide whether there is anything legitimate to retrain, before spending a runner on it.

A retrain is only honest when the *training evidence* has changed. In the 2026 preseason it
has not: `intrinsic-cb-hurdle-v1` was trained on 2014-2025, 2025 is the spent final holdout
(ADR-025, ADR-036), and 2026 has not been played. Retraining now would either reproduce the
same artifact from the same rows, or — much worse — quietly pull partial in-season 2026
outcomes into a training corpus and call the result an improvement.

So this gate answers one question with evidence rather than with a calendar:

    Is there a season after the model's last training season whose fantasy horizon is
    COMPLETE in the upstream weekly statistics?

A season that is unplayed (nflverse answers 404) or in progress (the weekly file stops short
of the horizon's last week) is **not** new evidence. Only a finished season is. The gate is
deliberately conservative in both directions it can be wrong about: a missing file is "no",
and a short file is "no".

It also reports whether the feature contract still matches the artifact, because a retrain
against a moved feature schema is a different decision that needs its own evaluation design
rather than a scheduled job.

    uv run python scripts/retrain_gate.py --model models/production/intrinsic-cb-hurdle-v1
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ffdraft.features.dictionary import feature_schema_hash
from ffdraft.modeling.frozen import (
    PRODUCTION_LAST_TRAINING_SEASON,
    PRODUCTION_SEASON,
)
from ffdraft.scoring.horizon import fantasy_horizon


def _season_is_complete(season: int) -> tuple[bool, str]:
    """Has ``season`` been played to the end of the fantasy horizon the labels use?

    The horizon, not the NFL calendar: `ffdraft.scoring.horizon` is what the label builder
    sums over, so "complete" has to mean complete *for a label*, and the horizon moved from
    weeks 1-16 to 1-17 at 2021.
    """
    import nflreadpy

    horizon = fantasy_horizon(season)
    try:
        frame = nflreadpy.load_player_stats(seasons=[season], summary_level="week")
    except Exception as error:  # noqa: BLE001 - any upstream failure means "no evidence"
        return False, f"weekly statistics unavailable for {season} ({type(error).__name__})"
    if frame.is_empty():
        return False, f"weekly statistics for {season} are empty"
    weeks = (
        frame.filter(frame["season_type"] == "REG")["week"]
        if "season_type" in frame
        else frame["week"]
    )
    observed = int(weeks.max() or 0)
    if observed < horizon.last_week:
        return False, (
            f"{season} is in progress: weekly statistics reach week {observed}, "
            f"the fantasy horizon ends at week {horizon.last_week}"
        )
    return True, f"{season} is complete through week {observed} (horizon ends {horizon.last_week})"


def evaluate(model_dir: Path, *, check_sources: bool) -> dict[str, Any]:
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    trained = sorted(int(season) for season in metadata["training_seasons"])
    last_trained = trained[-1]

    verdict: dict[str, Any] = {
        "model_version": metadata["model_version"],
        "training_seasons": f"{trained[0]}-{last_trained}",
        "last_training_season": last_trained,
        "frozen_last_training_season": PRODUCTION_LAST_TRAINING_SEASON,
        "production_season": PRODUCTION_SEASON,
        "feature_set_version": metadata["feature_set_version"],
        "feature_set_hash": metadata["feature_set_hash"],
        "artifact_feature_schema_hash": metadata["feature_schema_hash"],
        "code_feature_schema_hash": feature_schema_hash(),
        "candidate_seasons": [],
        "new_evidence": False,
        "should_retrain": False,
        "reasons": [],
    }

    if verdict["artifact_feature_schema_hash"] != verdict["code_feature_schema_hash"]:
        verdict["reasons"].append(
            "the feature schema in code no longer matches the production artifact; that is a "
            "new evaluation design (ADR-025/ADR-036), not a scheduled retrain",
        )

    candidates = list(range(last_trained + 1, PRODUCTION_SEASON + 1))
    if not candidates:
        verdict["reasons"].append(
            f"no season exists after the model's last training season ({last_trained})",
        )
        return verdict

    for season in candidates:
        if not check_sources:
            verdict["candidate_seasons"].append(
                {"season": season, "complete": None, "detail": "source check skipped"},
            )
            continue
        complete, detail = _season_is_complete(season)
        verdict["candidate_seasons"].append(
            {"season": season, "complete": complete, "detail": detail},
        )
        if complete:
            verdict["new_evidence"] = True

    if verdict["new_evidence"]:
        verdict["should_retrain"] = True
        verdict["reasons"].append(
            "a completed season exists that the production model has never seen; a candidate "
            "run is legitimate. Promotion still needs its own holdout protocol (ADR-025).",
        )
    else:
        verdict["reasons"].append(
            "no completed season exists beyond the training corpus, so retraining could only "
            "reproduce the same artifact or consume unplayed/in-season outcomes",
        )
    return verdict


def render(verdict: dict[str, Any]) -> str:
    lines = [
        "| | |",
        "|---|---|",
        f"| Production model | `{verdict['model_version']}` |",
        f"| Trained on | `{verdict['training_seasons']}` |",
        f"| Target season | `{verdict['production_season']}` |",
        f"| Feature set | `{verdict['feature_set_version']}` (`{verdict['feature_set_hash']}`) |",
        (
            f"| Feature schema | artifact `{verdict['artifact_feature_schema_hash']}`, "
            f"code `{verdict['code_feature_schema_hash']}` |"
        ),
        "",
    ]
    if verdict["candidate_seasons"]:
        lines.extend(["| season | complete | detail |", "|---|---|---|"])
        for row in verdict["candidate_seasons"]:
            mark = {True: "yes", False: "**no**", None: "—"}[row["complete"]]
            lines.append(f"| {row['season']} | {mark} | {row['detail']} |")
        lines.append("")
    verdict_line = (
        "**Retrain: candidate run is legitimate.**"
        if verdict["should_retrain"]
        else "**Retrain: nothing to do — exiting cleanly.**"
    )
    lines.append(verdict_line)
    lines.append("")
    lines.extend(f"- {reason}" for reason in verdict["reasons"])
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models/production/intrinsic-cb-hurdle-v1"),
    )
    parser.add_argument(
        "--skip-source-check",
        action="store_true",
        help="do not call nflverse; every candidate season is reported as unknown",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--summary-out", type=Path, default=None)
    args = parser.parse_args(argv)

    verdict = evaluate(args.model, check_sources=not args.skip_source_check)
    print(json.dumps(verdict, indent=2))
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"should_retrain={'true' if verdict['should_retrain'] else 'false'}\n")
            handle.write(f"model_version={verdict['model_version']}\n")
            handle.write(f"last_training_season={verdict['last_training_season']}\n")
    if args.summary_out is not None:
        with args.summary_out.open("a", encoding="utf-8") as handle:
            handle.write("## Retrain evidence gate\n\n")
            handle.write(render(verdict))
    # Exit 0 either way: "nothing to retrain" is a correct outcome, not a failure.
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through tests/unit
    raise SystemExit(main())
