"""The weekly start/sit model card (ADR-096).

Generated, never written by hand, for the reason every card in `models/cards/` is: a number in
a card that no command produces is a number that can drift. Every value is read from the two
committed experiment reports, from the production artifact's own metadata, or from the frozen
declarations in :mod:`ffdraft.weekly.frozen`.

`docs/MODELING.md` section 22 lists what a card must carry. This one adds what a decision-layer
model makes necessary: the measurements the page computes with, and the one-way-flow statement
that keeps it out of every board.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ffdraft.timeutil import isoformat_utc, utc_now
from ffdraft.weekly.frozen import (
    BASELINE_IDS,
    FEATURE_FAMILIES,
    FEATURE_FAMILY_LABELS,
    PROMOTION_RULE,
    TAIL_RULE,
    WEEKLY_CANDIDATE_VERSION,
    WEEKLY_DISTRIBUTION_RULE_VERSION,
    WEEKLY_FEATURE_SET_VERSION,
    WEEKLY_MODEL_VERSION,
    WEEKLY_NUM_BOOST_ROUND,
    WEEKLY_PARAMETERS,
    WEEKLY_QUANTILE_LEVELS,
    WEEKLY_SEED,
    WEEKLY_TARGET_RULE_VERSION,
    WeeklySpec,
    weekly_feature_set_hash,
)

__all__ = ["WEEKLY_CARD_VERSION", "build_weekly_card", "weekly_card_markdown", "write_weekly_card"]

WEEKLY_CARD_VERSION = "weekly_model_card_v1"

_BASELINE_LABELS = {
    "b0_season_rate": "B0 season rate",
    "b1_recent_form": "B1 recent form (last 3)",
    "b2_rate_x_vegas": "B2 shrunk rate x implied team total",
}


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _passed(report: Mapping[str, Any]) -> bool:
    return bool(report.get("verdict", {}).get("passed"))


def build_weekly_card(
    *,
    development: Mapping[str, Any],
    final: Mapping[str, Any],
    production: Mapping[str, Any],
    artifact_sha256: str | None,
    git_sha: str,
) -> dict[str, Any]:
    """Assemble the machine-readable card from the committed reports and the artifact."""
    accepted = _passed(development) and _passed(final) and bool(production)
    groups = production.get("groups", [])
    return {
        "production_status": (
            "ACCEPTED — weekly_promotion_v1 passed on the development folds and on the sealed "
            "2025 season; the production fit is the artifact this card describes (ADR-096)."
            if accepted
            else "NOT ACCEPTED — a verdict failed or no production artifact exists."
        ),
        "card_version": WEEKLY_CARD_VERSION,
        "model_version": WEEKLY_MODEL_VERSION,
        "candidate_version": WEEKLY_CANDIDATE_VERSION,
        "configuration_hash": WeeklySpec().configuration_hash(),
        "feature_set": {"version": WEEKLY_FEATURE_SET_VERSION, "hash": weekly_feature_set_hash()},
        "generated_at_utc": isoformat_utc(utc_now()),
        "git_sha": git_sha,
        "purpose": (
            "Estimate the distribution of a player's fantasy points in his next game, given "
            "that he plays, so that two to four players can be compared for one lineup slot "
            "at the manager's own matchup margin. Decision support for a weekly start/sit "
            "call, not a certainty and not a player value."
        ),
        "grain": "season x target_week x player_id x scoring_preset",
        "target": {
            "version": WEEKLY_TARGET_RULE_VERSION,
            "definition": (
                "fantasy points in the week after the cutoff, for players who appeared "
                "(a stats row or an offensive snap)"
            ),
        },
        "one_way_flow": (
            "A decision-layer model. It reads the rest-of-season snapshot and the week's game; "
            "no draft or rest-of-season projection, VORP, rank, tier or Pick of the Week "
            "selection reads it (tests/leakage/test_weekly_firewall.py)."
        ),
        "data_sources": [
            "nflverse via nflreadpy: weekly player stats, snap counts, rosters (features, "
            "target and appearances)",
            "nflverse schedules: total and spread for the projected game (a model input)",
            "nflverse injury reports: printed beside a projection and measured for base rates; "
            "never a model input",
        ],
        "features": {
            "families": {
                family: {
                    "label": FEATURE_FAMILY_LABELS[family],
                    "features": list(names),
                }
                for family, names in FEATURE_FAMILIES.items()
            },
        },
        "forbidden": {
            "market_ranks": (
                "ADP, ECR and every crowd-rank proxy: audited by forbidden_reason over the "
                "weekly feature list, which may name only the three line features"
            ),
            "injury_report": "not an input; the target is points given that he plays",
            "future_information": (
                "opponent readings are point-in-time at the cutoff, shrunk over 4 games; "
                "lines are those posted for the game"
            ),
        },
        "architecture": {
            "family": (
                "LightGBM quantile boosters per position x scoring preset x level, monotone "
                "rearrangement, split-conformal offsets from the last training season"
            ),
            "levels": list(WEEKLY_QUANTILE_LEVELS),
            "parameters": dict(WEEKLY_PARAMETERS),
            "num_boost_round": WEEKLY_NUM_BOOST_ROUND,
            "seed": WEEKLY_SEED,
            "distribution_rule": {
                "version": WEEKLY_DISTRIBUTION_RULE_VERSION,
                "tail_lower_factor": TAIL_RULE["lower_factor"],
                "tail_upper_factor": TAIL_RULE["upper_factor"],
            },
            "tuning": "none; the configuration was frozen before any evidence (commit 4f62112)",
            "explanation": (
                "grouped TreeSHAP by feature family, plus baseline, calibration and "
                "rearrangement terms, summing to the published median"
            ),
        },
        "promotion": {
            "rule": PROMOTION_RULE.to_dict(),
            "baselines": list(BASELINE_IDS),
            "development_verdict": development.get("verdict", {}),
            "holdout_verdict": final.get("verdict", {}),
            "holdout_authorization": final.get("authorization", {}),
        },
        "evaluation": {
            "folds": development.get("folds", []),
            "decision_pool_depth": development.get("decision_pool_depth", {}),
            "development": {
                "pooled": development.get("pooled", {}),
                "by_season": development.get("by_season", {}),
                "by_position": development.get("by_position", {}),
            },
            "holdout": {
                "pooled": final.get("pooled", {}),
                "by_position": final.get("by_position", {}),
                "calibration": final.get("diagnostics", {}).get("calibration", []),
            },
        },
        "production_fit": {
            "training_seasons": production.get("training_seasons", []),
            "calibration_season": production.get("calibration_season"),
            "fitted_at_utc": production.get("fitted_at_utc"),
            "refit_reason": production.get("refit_reason"),
            "groups": len(groups),
            "boosters": sum(len(group.get("boosters", [])) for group in groups),
            "training_rows": sum(int(group.get("training_rows", 0)) for group in groups),
            "metadata_sha256": artifact_sha256,
            "reproducibility": "two fits from the same dataset give byte-identical boosters",
        },
        "measurements": production.get("measurements", {}),
        "limitations": _limitations(),
    }


def _limitations() -> list[str]:
    return [
        "Points given that he plays. A Questionable player's projection is not discounted for "
        "the chance he sits; the page prints the designation's measured appearance rate beside "
        "it instead.",
        "No weather: nflverse records temperature and wind only after kickoff.",
        "Every training row had a posted total and spread, so the model cannot project a game "
        "without them (it would read a missing line as zero). Such a game is published as "
        "lines_pending with no distribution until the line is posted.",
        "A player with no appearance this season is projected from the rest-of-season "
        "snapshot's prior and role fields alone.",
        "The margin uncertainty is one number per slot, measured over a standard lineup. A "
        "league with unusual rosters has a different one.",
        "Same-game correlation is measured by position pair and applied through a Gaussian "
        "copula; a pair with too few rows is treated as independent and the page says so.",
        "The injury file's point-in-time behaviour is unprobed (config/source-registry.yaml), "
        "so the designation base rates could move slightly if nflverse revises rows. No "
        "projection reads them.",
    ]


def _number(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _metrics_table(pooled: Mapping[str, Mapping[str, Any]], order: Sequence[str]) -> list[str]:
    lines = [
        "| model | pinball | MAE (median) | pair accuracy | pair Brier | P10–P90 cover |",
        "|---|---|---|---|---|---|",
    ]
    for model in order:
        row = pooled.get(model)
        if row is None:
            continue
        label = _BASELINE_LABELS.get(model, f"{model} (candidate)")
        lines.append(
            f"| {label} | {_number(row.get('pinball'))} | {_number(row.get('mae_median'), 3)} | "
            f"{_number(row.get('pair_accuracy'))} | {_number(row.get('pair_brier'))} | "
            f"{_number(row.get('coverage_80'), 3)} |",
        )
    return [*lines, ""]


def weekly_card_markdown(card: Mapping[str, Any]) -> str:
    order = [card["candidate_version"], *BASELINE_IDS]
    evaluation = card["evaluation"]
    production = card["production_fit"]
    promotion = card["promotion"]
    lines = [
        f"# Model card — {card['model_version']}",
        "",
        f"Generated by `ffdraft weekly-model-card` at {card['generated_at_utc']} from the "
        f"committed reports and artifact (git `{card['git_sha']}`). Card version "
        f"`{card['card_version']}`.",
        "",
        f"**{card['production_status']}**",
        "",
        "## Purpose",
        "",
        card["purpose"],
        "",
        f"**Grain:** `{card['grain']}`. **Target** (`{card['target']['version']}`): "
        f"{card['target']['definition']}.",
        "",
        f"**One-way flow.** {card['one_way_flow']}",
        "",
        "## Data sources",
        "",
        *[f"- {source}" for source in card["data_sources"]],
        "",
        "## Features",
        "",
        f"Feature set `{card['feature_set']['version']}` (`{card['feature_set']['hash']}`), "
        f"configuration `{card['configuration_hash']}`.",
        "",
        "| family | features |",
        "|---|---|",
        *[
            f"| {family['label']} | {', '.join(f'`{name}`' for name in family['features'])} |"
            for family in card["features"]["families"].values()
        ],
        "",
        "**Not inputs:**",
        "",
        *[f"- **{key.replace('_', ' ')}** — {value}" for key, value in card["forbidden"].items()],
        "",
        "## Architecture",
        "",
        f"{card['architecture']['family']}. Levels "
        f"{', '.join(str(level) for level in card['architecture']['levels'])}; "
        f"{card['architecture']['num_boost_round']} rounds; seed {card['architecture']['seed']}. "
        f"Tuning: {card['architecture']['tuning']}. Explanation: "
        f"{card['architecture']['explanation']}.",
        "",
        "## Evaluation",
        "",
        f"Rolling origin, folds {', '.join(str(f.get('season')) for f in evaluation['folds'])}; "
        f"pairs are every same-position pair in each week's decision pool "
        f"({', '.join(f'{k} {v}' for k, v in evaluation['decision_pool_depth'].items())}), all "
        "three scoring presets.",
        "",
        "### Development, pooled 2020–2024",
        "",
        *_metrics_table(evaluation["development"]["pooled"], order),
        "### Sealed 2025 holdout",
        "",
        *_metrics_table(evaluation["holdout"]["pooled"], order),
        f"Holdout authorization reason: *{promotion['holdout_authorization'].get('reason', '—')}*",
        "",
        "### Sealed 2025, by position (candidate vs best baseline B2)",
        "",
        "| position | pairs | candidate accuracy | B2 accuracy | candidate pinball | B2 pinball |",
        "|---|---|---|---|---|---|",
    ]
    for position, models in evaluation["holdout"]["by_position"].items():
        mine = models.get(card["candidate_version"], {})
        b2 = models.get("b2_rate_x_vegas", {})
        lines.append(
            f"| {position} | {_number(mine.get('pairs'))} | {_number(mine.get('pair_accuracy'))} | "
            f"{_number(b2.get('pair_accuracy'))} | {_number(mine.get('pinball'))} | "
            f"{_number(b2.get('pinball'))} |",
        )
    lines.extend(
        [
            "",
            "### Calibration of the head-to-head (sealed 2025)",
            "",
            "| favourite probability | pairs | predicted | observed |",
            "|---|---|---|---|",
            *[
                f"| {row['low']:.2f}–{row['high']:.2f} | {row['pairs']:,} | "
                f"{row['predicted']:.3f} | {row['observed']:.3f} |"
                for row in evaluation["holdout"]["calibration"]
            ],
            "",
            "## Promotion",
            "",
            "| stage | clause | passed |",
            "|---|---|---|",
        ],
    )
    for stage, key in (("development", "development_verdict"), ("holdout", "holdout_verdict")):
        for clause, result in promotion[key].get("clauses", {}).items():
            lines.append(f"| {stage} | `{clause}` | {_number(result.get('passed'))} |")
    measurements = card["measurements"]
    margin = measurements.get("margin", {}).get("PPR", {}).get("margin_sd_by_slot", {})
    correlation = measurements.get("correlation", {}).get("pairs", {})
    injuries = {
        key: value for key, value in measurements.get("injuries", {}).items() if key != "_rule"
    }
    lines.extend(
        [
            "",
            "## Production fit",
            "",
            f"Seasons {', '.join(str(s) for s in production['training_seasons'])} "
            f"(calibration offsets from {production['calibration_season']}); "
            f"{production['groups']} position x preset groups, {production['boosters']} boosters, "
            f"{_number(production['training_rows'])} training rows. Fitted "
            f"{production['fitted_at_utc']} ({production['refit_reason']}). "
            f"`metadata.json` sha256 `{production['metadata_sha256']}`; every booster's digest "
            f"is checked at load. {production['reproducibility'].capitalize()}.",
            "",
            "## Published measurements",
            "",
            "Margin uncertainty by slot, PPR: "
            + ", ".join(f"{slot} {value}" for slot, value in sorted(margin.items()))
            + ".",
            "",
            "Same-game correlation (ρ): "
            + ", ".join(f"{key} {value.get('rho')}" for key, value in sorted(correlation.items()))
            + ".",
            "",
            "Designation appearance rates: "
            + ", ".join(
                f"{key} {100 * float(value.get('appearance_rate') or 0):.2f}% of "
                f"{int(value.get('reports') or 0):,}"
                for key, value in sorted(injuries.items())
            )
            + ".",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in card["limitations"]],
            "",
        ],
    )
    return "\n".join(lines)


def write_weekly_card(
    *,
    development_path: Path,
    final_path: Path,
    model_dir: Path,
    out_dir: Path,
    git_sha: str,
) -> list[Path]:
    """Write `models/cards/weekly-startsit-v1.{json,md}`."""
    metadata_path = model_dir / "metadata.json"
    card = build_weekly_card(
        development=_read(development_path),
        final=_read(final_path),
        production=_read(metadata_path),
        artifact_sha256=(
            hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            if metadata_path.is_file()
            else None
        ),
        git_sha=git_sha,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in (
        (f"{WEEKLY_MODEL_VERSION}.json", json.dumps(card, indent=2, sort_keys=True) + "\n"),
        (f"{WEEKLY_MODEL_VERSION}.md", weekly_card_markdown(card)),
    ):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
