"""The ``weekly-startsit-v2`` model card (ADR-099).

Generated, never written by hand, like every card in ``models/cards/``: every value is read
from the committed development report (``docs/experiments/weekly-startsit-v2``), from the
shadow artifact's own metadata when one was fitted, and from the frozen declarations in
:mod:`ffdraft.weekly.frozen_v2`. A card exists whatever development decided: a rejected
candidate's card records what each family measured and why nothing was fitted, so the
decision can be read without re-running it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ffdraft.timeutil import isoformat_utc, utc_now
from ffdraft.weekly.frozen_v2 import (
    CANDIDATE_VARIANTS,
    DECISION_CUTOFF,
    FAMILY_SELECTION_RULE,
    PROMOTION_RULE_V2,
    PROSPECTIVE_HOLDOUT,
    V2_FAMILIES,
    V2_FAMILY_LABELS,
    WEATHER_PARITY_RULE,
    WEEKLY_V2_FEATURE_SET_VERSION,
    WEEKLY_V2_FROZEN_AT_UTC,
    WEEKLY_V2_MODEL_VERSION,
    v2_spec,
)

__all__ = ["WEEKLY_V2_CARD_VERSION", "build_weekly_v2_card", "write_weekly_v2_card"]

WEEKLY_V2_CARD_VERSION = "weekly_v2_model_card_v1"

#: The freeze commit: the rules below were committed here, before the development run.
FREEZE_COMMIT = "f62f849"


def _read(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _status(report: Mapping[str, Any], artifact: Mapping[str, Any]) -> str:
    if not report:
        return "NOT EVALUATED — no development report"
    if report.get("outcome") != "selected":
        return (
            "REJECTED AT DEVELOPMENT — no family beat v1 by the frozen rule; no artifact was "
            "fitted and v1 stays in production"
        )
    if not artifact:
        return "SELECTED AT DEVELOPMENT — shadow artifact not yet fitted"
    return (
        "SHADOW — selected at development; v1 stays in production until the prospective "
        "holdout (2026, after the freeze) promotes or rejects this model"
    )


def build_weekly_v2_card(
    *,
    report_path: Path,
    model_dir: Path | None,
    prospective_path: Path | None = None,
    weather_parameters_digest: str,
    generated_at: str | None = None,
    git_sha: str = "unknown",
) -> dict[str, Any]:
    report = _read(report_path)
    metadata_path = None if model_dir is None else model_dir / "metadata.json"
    artifact = _read(metadata_path)
    prospective = _read(prospective_path)
    families = tuple(report.get("v2_families") or ())
    spec = v2_spec(families, weather_parameters_digest=weather_parameters_digest)
    groups = list(artifact.get("groups") or [])
    selection = report.get("selection") or {}
    incremental = {
        family: {
            "label": V2_FAMILY_LABELS[family],
            "pinball_difference": result["clauses"]["pinball_below_v1"]["difference"],
            "interval": [
                result["clauses"]["pinball_interval_above_zero"]["lower"],
                result["clauses"]["pinball_interval_above_zero"]["upper"],
            ],
            "fold_wins": result["clauses"]["pinball_fold_wins"]["wins"],
            "accuracy_difference": result["clauses"]["decision_not_worse"]["accuracy"]
            - result["clauses"]["decision_not_worse"]["accuracy_v1"],
            "brier_difference": result["clauses"]["decision_not_worse"]["brier"]
            - result["clauses"]["decision_not_worse"]["brier_v1"],
            "selected": bool(result["passed"]),
        }
        for family, result in (selection.get("families") or {}).items()
    }
    return {
        "card_version": WEEKLY_V2_CARD_VERSION,
        "generated_at_utc": generated_at or isoformat_utc(utc_now()),
        "git_sha": git_sha,
        "model_version": WEEKLY_V2_MODEL_VERSION,
        "status": _status(report, artifact),
        "intended_use": (
            "Shadow evaluation only: weekly-startsit-v1's distribution plus "
            + (
                " and ".join(V2_FAMILY_LABELS[family].lower() for family in families)
                if families
                else "no family"
            )
            + ", predicted beside weekly-startsit-v1 into a private record. Nothing published "
            "reads it until weekly_promotion_v2 promotes it."
        ),
        "not_for": [
            "the draft or rest-of-season boards, tiers or values (one-way flow, AGENTS.md 1)",
            "any public number before promotion",
            "a causal reading of a weather or injury effect",
        ],
        "frozen": {
            "commit": FREEZE_COMMIT,
            "frozen_at_utc": WEEKLY_V2_FROZEN_AT_UTC,
            "feature_set": WEEKLY_V2_FEATURE_SET_VERSION,
            "families": {key: list(value) for key, value in V2_FAMILIES.items()},
            "variants": list(CANDIDATE_VARIANTS),
            "family_selection": FAMILY_SELECTION_RULE.to_dict(),
            "promotion": PROMOTION_RULE_V2.to_dict(),
            "prospective_holdout": PROSPECTIVE_HOLDOUT.to_dict(),
            "decision_cutoff": dict(DECISION_CUTOFF),
            "weather_parity": WEATHER_PARITY_RULE.to_dict(),
            "weather_parameters_digest": weather_parameters_digest,
        },
        "selected_families": list(families),
        "configuration_hash": spec.configuration_hash() if families else None,
        "development": {
            "outcome": report.get("outcome"),
            "folds": report.get("folds", []),
            "pooled": report.get("pooled", {}),
            "incremental_value_over_v1": incremental,
            "union": report.get("union"),
            "development_verdict": report.get("development_verdict"),
            "previously_examined": report.get("previously_examined"),
        },
        "shadow_artifact": (
            {
                "training_seasons": artifact.get("training_seasons", []),
                "fitted_at_utc": artifact.get("fitted_at_utc"),
                "configuration_hash": artifact.get("configuration_hash"),
                "groups": len(groups),
                "boosters": sum(len(group.get("boosters", [])) for group in groups),
                "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest()
                if metadata_path is not None and metadata_path.is_file()
                else None,
            }
            if artifact
            else None
        ),
        "prospective": prospective or {"status": "pending — minimum evidence not yet met"},
        "limitations": _limitations(families),
    }


def _limitations(families: tuple[str, ...]) -> list[str]:
    measured = [family for family in V2_FAMILIES if family not in families]
    notes = [
        "Measured but not selected (no value over v1 beyond noise by the frozen rule; v1 "
        "already reads the sportsbook lines, which may price them — not tested here): "
        + (", ".join(V2_FAMILY_LABELS[family] for family in measured) or "none")
        + ". Their inputs are still published as context, without points.",
        "Game-day inactives arrive after every refresh and are not inputs.",
        "v1's roof input, which v2 also reads, follows a verified fixed venue roof where the "
        "schedule contradicts it (nflverse's 2026 dome for the MCG, the Stade de France and "
        "the Allianz Arena, all open to the sky; ADR-099 amendment). v1 and v2 read the same "
        "value, so the prospective comparison stays paired.",
    ]
    if "lineup" in families or "defense" in families:
        notes += [
            "The injury report is point in time for 2017-2024 to 24 of 44,356 rows; 2025 rows "
            "carry no timestamp and are unverified (docs/DATA_SOURCES.md 20.3).",
            "Starters are lagged snap-share leaders; a starter returning from a long absence, "
            "or a mid-week signing, is not one until he plays.",
            "A team whose report carries no game status is unknown (null) on every health "
            "input, never healthy.",
        ]
    if "weather" in families:
        notes += [
            "Training weather is the game book's recorded kickoff weather mapped to a "
            "day-before forecast's error (289 open-air games, 2024-2025); serving reads NWS "
            "or Open-Meteo, whose error differs. Precipitation's mapping rests on 18 wet games.",
            "Retractable-roof and unverified venues carry no weather at training or serving.",
        ]
    return notes


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def weekly_v2_card_markdown(card: Mapping[str, Any]) -> str:
    development = card["development"]
    lines = [
        f"# Model card — {card['model_version']}",
        "",
        f"**Status:** {card['status']}.",
        "",
        f"Generated by `uv run ffdraft weekly-v2-model-card` from the committed evidence "
        f"(card `{card['card_version']}`). Rules frozen in commit `{card['frozen']['commit']}` "
        f"(`src/ffdraft/weekly/frozen_v2.py`) before the development run.",
        "",
        "## Intended use",
        "",
        card["intended_use"],
        "",
        "Not for: " + "; ".join(card["not_for"]) + ".",
        "",
        "## Candidate families",
        "",
    ]
    for family, features in card["frozen"]["families"].items():
        lines.append(f"- **{V2_FAMILY_LABELS[family]}** (`{family}`): " + ", ".join(features))
    lines += [
        "",
        f"Selected: **{', '.join(card['selected_families']) or 'none'}**; configuration hash "
        f"`{card['configuration_hash'] or '—'}`; weather map digest "
        f"`{card['frozen']['weather_parameters_digest']}`.",
        "",
        "## Each family's incremental value over v1 (development folds 2020–2024)",
        "",
        "| family | Δ pinball (v1 − v1+f) | 95% interval | fold wins | Δ accuracy | Δ Brier "
        "| selected |",
        "|---|---|---|---|---|---|---|",
    ]
    for value in development["incremental_value_over_v1"].values():
        lines.append(
            f"| {value['label']} | {_fmt(value['pinball_difference'], 5)} | "
            f"[{_fmt(value['interval'][0], 5)}, {_fmt(value['interval'][1], 5)}] | "
            f"{value['fold_wins']}/5 | {_fmt(value['accuracy_difference'], 5)} | "
            f"{_fmt(value['brier_difference'], 5)} | {'yes' if value['selected'] else 'no'} |",
        )
    lines += [
        "",
        "## Pooled development metrics",
        "",
        "| model | pinball | pair accuracy | pair Brier | P10–P90 |",
        "|---|---|---|---|---|",
    ]
    for model, values in development["pooled"].items():
        lines.append(
            f"| {model} | {_fmt(values.get('pinball'))} | {_fmt(values.get('pair_accuracy'))} | "
            f"{_fmt(values.get('pair_brier'))} | {_fmt(values.get('coverage_80'), 3)} |",
        )
    examined = development.get("previously_examined")
    if examined:
        lines += [
            "",
            f"2025 (previously examined, decides nothing): consistent with development — "
            f"**{examined['consistent']}**.",
        ]
    artifact = card.get("shadow_artifact")
    lines += ["", "## Shadow artifact", ""]
    if artifact:
        lines.append(
            f"Seasons {artifact['training_seasons']}, {artifact['groups']} groups, "
            f"{artifact['boosters']} boosters, metadata sha256 `{artifact['metadata_sha256']}`.",
        )
    else:
        lines.append("None fitted.")
    lines += [
        "",
        "## Prospective holdout",
        "",
        f"Rule `{card['frozen']['promotion']['version']}`; minimum "
        f"{card['frozen']['prospective_holdout']['min_weeks']} weeks, "
        f"{card['frozen']['prospective_holdout']['min_rows']} rows, "
        f"{card['frozen']['prospective_holdout']['min_pairs']} pairs; status: "
        f"{card['prospective'].get('status') or card['prospective'].get('outcome')}.",
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in card["limitations"]],
        "",
    ]
    return "\n".join(lines)


def write_weekly_v2_card(
    *,
    report_path: Path,
    model_dir: Path | None,
    out_dir: Path,
    weather_parameters_digest: str,
    prospective_path: Path | None = None,
    git_sha: str = "unknown",
) -> list[Path]:
    card = build_weekly_v2_card(
        report_path=report_path,
        model_dir=model_dir,
        prospective_path=prospective_path,
        weather_parameters_digest=weather_parameters_digest,
        git_sha=git_sha,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{WEEKLY_V2_MODEL_VERSION}.json"
    json_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = out_dir / f"{WEEKLY_V2_MODEL_VERSION}.md"
    md_path.write_text(weekly_v2_card_markdown(card), encoding="utf-8")
    return [json_path, md_path]
