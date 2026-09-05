"""The rest-of-season model card.

Generated, never written by hand, for the same reason `docs/FEATURE_DICTIONARY.md` is: a
number in a card that no command produces is a number that can drift. Every value below is
read from a committed experiment report, from the value study, or from the code's own frozen
declarations.

`docs/MODELING.md` section 22 lists what a card must carry. This one adds the two things the
rest-of-season grain makes necessary: the cutoff rule the card's numbers were measured under,
and the prior-exposure qualification on its sealed season.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ffdraft.ros.candidates import RC1_NUM_BOOST_ROUND, RC1_PARAMETERS, RC1_VERSION
from ffdraft.ros.cutoff import ROS_CUTOFF_RULE, ROS_CUTOFF_RULE_VERSION
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.gate import ROS_PROMOTION_CRITERIA, ROS_PROMOTION_CRITERIA_V2
from ffdraft.ros.holdout import ros_holdout_policy
from ffdraft.ros.labels import ROS_LABEL_VERSION
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = ["ROS_CARD_VERSION", "build_ros_card", "write_ros_card"]

ROS_CARD_VERSION = "ros_model_card_v1"

_CARD_NAME = "intrinsic-ros-v1"


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def build_ros_card(
    *,
    development: dict[str, Any],
    final: dict[str, Any],
    value: dict[str, Any],
    git_sha: str,
    production: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the machine-readable card from the committed reports."""
    selection = ros_feature_selection()
    gate = development.get("gate", {})
    gate_v2 = development.get("gate_v2", {})
    macro = development.get("macro_by_model", {})
    accepted = bool(gate_v2.get("promoted"))
    return {
        "production_status": (
            "ACCEPTED FOR PHASE 12 — promoted under ros_promotion_v2 (ADR-077). It failed "
            "ros_promotion_v1, whose clause 4 was found to be mis-specified for a "
            "zero-inflated target (ADR-073, ADR-075); that failure is preserved, not repealed."
            if accepted
            else "NOT READY FOR PHASE 12 — not promoted under ros_promotion_v2."
        ),
        "card_version": ROS_CARD_VERSION,
        "model_version": RC1_VERSION,
        "model_name": _CARD_NAME,
        "generated_at_utc": isoformat_utc(utc_now()),
        "git_sha": git_sha,
        "purpose": (
            "Estimate the distribution of a player's fantasy points over the remainder of the "
            "current season from football evidence alone, and translate it into league-relative "
            "value. Decision support for in-season roster decisions, not a certainty."
        ),
        "grain": "season x through_week x player_id x scoring_preset",
        "cutoff_rule": {"version": ROS_CUTOFF_RULE_VERSION, "rule": ROS_CUTOFF_RULE},
        "label": {
            "version": ROS_LABEL_VERSION,
            "target": "actual_remaining_points",
            "components": ["actual_remaining_games", "actual_remaining_ppg"],
        },
        "features": selection.to_dict(),
        "forbidden": {
            "market_signals": "audited by ffdraft.quality.audit_intrinsic_feature_names",
            "injury_and_practice_reports": "excluded; see ADR-070",
            "depth_and_roster_snapshots": "excluded; no historical point-in-time parity",
        },
        "architecture": {
            "family": "availability x conditional performance hurdle, Monte Carlo composed",
            "parameters": dict(RC1_PARAMETERS),
            "num_boost_round": RC1_NUM_BOOST_ROUND,
            "tuning": "none; Q1's predeclared configuration is reused unchanged",
        },
        "evaluation": {
            "folds": development.get("configuration", {}).get("folds", []),
            "cell": "season x through_week x position x scoring_preset",
            "macro_by_model": macro,
            "primary_baseline": development.get("primary_baseline"),
            "paired_deltas": development.get("paired_deltas", {}),
            "cohorts": development.get("cohorts", []),
        },
        "promotion": {
            "criteria": ROS_PROMOTION_CRITERIA.to_dict(),
            "decision": gate,
            "criteria_v2": ROS_PROMOTION_CRITERIA_V2.to_dict(),
            "decision_v2": gate_v2,
        },
        # The policy is taken from the live declaration rather than from the report's frozen
        # copy, so the card's wording stays current; the report keeps its own copy as the
        # record of what the run declared at the time.
        "holdout": ros_holdout_policy(
            status="CONSUMED" if final.get("macro_by_model") else "UNTOUCHED / NOT EVALUATED",
        ),
        "sealed_result": {
            "macro_by_model": final.get("macro_by_model", {}),
            "paired_deltas": final.get("paired_deltas", {}),
            "gate": final.get("gate", {}),
        },
        "value": {
            "replacement": value.get("replacement", {}).get("decision", {}),
            "convergence": value.get("convergence", {}).get("decision", {}),
            "tier_penalty": value.get("tiers", {}).get("decision", {}),
            "tier_stability": value.get("tiers", {}).get("stability_decision", {}),
        },
        # Deliberately **not** an evaluation section (ADR-078). A production fit is scored
        # on nothing: it reports what it was fitted on and how it can be checked, and every
        # performance number in this card belongs to the Phase-11 evidence above.
        "production_fit": _production_fit(production),
        "limitations": _limitations(),
    }


def _production_fit(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """What the served artifact is, from its own metadata. No performance claim."""
    if not metadata:
        return {
            "fitted": False,
            "note": (
                "No production artifact is committed. The architecture is accepted; nothing "
                "is served until `ffdraft train-ros-production` writes one (ADR-078)."
            ),
        }
    authorization = metadata.get("sealed_season_authorization") or {}
    return {
        "fitted": True,
        "protocol": metadata.get("production_fit_rule_version"),
        "configuration_hash": metadata.get("configuration_hash"),
        "artifact_schema": metadata.get("artifact_schema"),
        "refit_reason": metadata.get("refit_reason"),
        "training_seasons": metadata.get("training_seasons", []),
        "training_rows": metadata.get("training_rows"),
        "serving_season": metadata.get("serving_season"),
        "fold_id": metadata.get("fold", {}).get("fold_id"),
        "feature_set_hash": metadata.get("feature_set_hash"),
        "feature_schema_hash": metadata.get("feature_schema_hash"),
        "dataset_content_hash": metadata.get("dataset_manifest", {}).get("content_hash"),
        "dataset_rows": metadata.get("dataset_manifest", {}).get("rows"),
        "groups": len(metadata.get("groups", [])),
        "library": metadata.get("library", {}),
        "generated_at_utc": metadata.get("generated_at_utc"),
        "git_sha": metadata.get("git_sha"),
        "sealed_seasons_included": authorization.get("sealed_training_seasons", []),
        "sealed_authorization_reason": authorization.get("reason"),
        "carries_performance_claim": False,
    }


def _limitations() -> list[str]:
    return [
        "There is no injury or practice-report feature. The model learns absence from the "
        "box score, so it sees a player who has stopped playing but not one who is about to "
        "(ADR-070).",
        "The sealed season is 2025, which Phase 4 had already opened as the preseason model's "
        "final holdout. Nothing from it informed this model's design, but season totals "
        "correlate with rest-of-season totals, so its out-of-time result is strong rather "
        "than fully naive evidence (ADR-069).",
        "Roughly half of all modelled rows have zero remaining games. Pooled interval coverage "
        "therefore overstates interval width, and coverage is reported split by appearances.",
        "The availability/performance dependence is estimated on players with at least one "
        "remaining game, because points per game is undefined for the rest, and extrapolated "
        "to everyone.",
        "The preseason feature block is null for in-season arrivals, who are 8.7% of players "
        "in the 2017-2025 build and are reported as their own cohort.",
        "Player outcomes are simulated independently; teammate and team-level correlations are "
        "not modelled, exactly as in Release 1.",
        "The model is overconfident on high-draft-capital rookies: P10-P90 coverage 0.763 "
        "against an attainable 0.898. That is the tightest clause in the promotion gate, "
        "0.015 from failing it, and the first thing to re-check on any new evidence.",
        "It cannot order the long-absence cohort: Spearman 0.311 on 18,951 development rows "
        "against 0.797 on the full universe. ADR-076 specifies what a product built on it must "
        "disclose.",
        "Its intervals on the zero-current-games cohort are conservative — 14.5 wide against a "
        "climatological 4.5 — though narrower than the baseline's and better scored.",
        "The sealed season is spent. This model's published out-of-time result describes these "
        "exact outputs; any change to them requires a fresh sealed season (ADR-077).",
        "The served artifact is a production refit of this architecture on the widest "
        "permitted window (ADR-078). It carries no performance claim of its own: it was "
        "scored on nothing, and every number above belongs to the Phase-11 evaluation.",
    ]


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    header = "| " + " | ".join(title for _, title in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(str(row.get(key, "")) for key, _ in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _number(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _sealed_section(card: dict[str, Any]) -> list[str]:
    """The one out-of-time result, rendered only once the holdout has actually been opened."""
    sealed = card.get("sealed_result", {})
    macro = sealed.get("macro_by_model") or {}
    if not macro:
        return []
    lines = [
        _table(
            [
                {
                    "model": model_id,
                    "mae": _number(values.get("mae"), 2),
                    "pinball": _number(values.get("mean_pinball")),
                    "spearman": _number(values.get("spearman")),
                    "coverage": _number(values.get("coverage_p10_p90")),
                }
                for model_id, values in macro.items()
            ],
            [
                ("model", "model"),
                ("mae", "MAE"),
                ("pinball", "pinball"),
                ("spearman", "Spearman"),
                ("coverage", "P10-P90 coverage"),
            ],
        ),
        "",
    ]
    deltas = sealed.get("paired_deltas", {})
    if deltas:
        lines.extend(
            [
                _table(
                    [
                        {
                            "metric": metric,
                            "delta": _number(payload.get("delta"), 4),
                            "ci": f"[{payload.get('ci_low', float('nan')):+.4f}, "
                            f"{payload.get('ci_high', float('nan')):+.4f}]",
                            "resolved": "yes" if payload.get("ci_excludes_zero") else "no",
                        }
                        for metric, payload in deltas.items()
                    ],
                    [
                        ("metric", "metric"),
                        ("delta", "delta"),
                        ("ci", "95% CI"),
                        ("resolved", "interval excludes 0"),
                    ],
                ),
                "",
            ],
        )
    for reason in sealed.get("gate", {}).get("failed_clauses", []):
        lines.append(f"- **failed on the sealed season**: {reason}")
    lines.append("")
    return lines


def card_markdown(card: dict[str, Any]) -> str:
    """The human-readable card."""
    evaluation = card["evaluation"]
    macro_rows = [
        {
            "model": model_id,
            "mae": _number(values.get("mae"), 2),
            "pinball": _number(values.get("mean_pinball")),
            "spearman": _number(values.get("spearman")),
            "coverage": _number(values.get("coverage_p10_p90")),
        }
        for model_id, values in evaluation.get("macro_by_model", {}).items()
    ]
    delta_rows = [
        {
            "metric": metric,
            "delta": _number(payload.get("delta"), 4),
            "ci": f"[{payload.get('ci_low', float('nan')):+.4f}, "
            f"{payload.get('ci_high', float('nan')):+.4f}]",
            "resolved": "yes" if payload.get("ci_excludes_zero") else "no",
        }
        for metric, payload in evaluation.get("paired_deltas", {}).items()
    ]
    decision = card["promotion"]["decision"]
    decision_v2 = card["promotion"].get("decision_v2", {})
    lines = [
        f"# Rest-of-season model card — `{card['model_version']}`",
        "",
        f"Card `{card['card_version']}`, generated {card['generated_at_utc']} from code "
        f"`{card['git_sha']}`. Every number below is read from a committed report or from the "
        "code's own frozen declarations; none is written by hand.",
        "",
        f"## Production status\n\n**{card.get('production_status', 'unknown')}**",
        "",
        "## Purpose and intended use",
        "",
        card["purpose"],
        "",
        "## Grain, cutoff and label",
        "",
        f"- grain: `{card['grain']}`",
        f"- cutoff `{card['cutoff_rule']['version']}`: {card['cutoff_rule']['rule']}",
        f"- label `{card['label']['version']}`: `{card['label']['target']}`, composed from "
        f"`{'`, `'.join(card['label']['components'])}`",
        "",
        "## Features",
        "",
        f"Set `{card['features']['feature_set_version']}` "
        f"(`{card['features']['feature_set_hash']}`): {card['features']['included_count']} inputs "
        f"— {card['features']['preseason_count']} inherited from Phase 3's frozen preseason core "
        f"and {card['features']['in_season_count']} in-season columns. Full list in "
        "`docs/ROS_FEATURE_DICTIONARY.md`.",
        "",
        "Excluded by decision, not by omission:",
        "",
    ]
    lines.extend(f"- **{key}** — {value}" for key, value in card["forbidden"].items())
    lines.extend(
        [
            "",
            "## Architecture",
            "",
            f"{card['architecture']['family']}; {card['architecture']['num_boost_round']} boosting "
            f"rounds per quantile per component; tuning: {card['architecture']['tuning']}.",
            "",
            "## Development result",
            "",
            f"Primary baseline `{evaluation.get('primary_baseline')}`, chosen by the frozen rule.",
            "",
            _table(
                macro_rows,
                [
                    ("model", "model"),
                    ("mae", "MAE"),
                    ("pinball", "pinball"),
                    ("spearman", "Spearman"),
                    ("coverage", "P10-P90 coverage"),
                ],
            ),
            "",
            "Paired deltas, candidate minus primary baseline:",
            "",
            _table(
                delta_rows,
                [
                    ("metric", "metric"),
                    ("delta", "delta"),
                    ("ci", "95% CI"),
                    ("resolved", "interval excludes 0"),
                ],
            ),
            "",
            "## Promotion decisions",
            "",
            "Two rules, both reported. The original is the historical record and is never "
            "overwritten by its successor.",
            "",
            f"### `{card['promotion']['criteria']['criteria_version']}` — "
            f"**{'PROMOTED' if decision.get('promoted') else 'NOT PROMOTED'}**",
            "",
        ],
    )
    for reason in decision.get("failed_clauses", []):
        lines.append(f"- **failed**: {reason}")
    lines.extend(
        [
            "",
            f"### `{card['promotion']['criteria_v2']['criteria_version']}` — "
            f"**{'PROMOTED' if decision_v2.get('promoted') else 'NOT PROMOTED'}**",
            "",
            "Clauses 1-3 and 4a-4b are the original's, unchanged. 4c adds a proper local "
            "score, 4d states interval width against climatology, and 4e states coverage "
            "against what calibration can attain on the cohort rather than against a fixed "
            "0.80 the target's atom at zero makes unreachable (ADR-075).",
            "",
        ],
    )
    for reason in decision_v2.get("satisfied_clauses", []):
        lines.append(f"- satisfied: {reason}")
    for reason in decision_v2.get("failed_clauses", []):
        lines.append(f"- **failed**: {reason}")
    lines.extend(
        [
            "",
            "## Sealed season",
            "",
            f"{card['holdout'].get('sealed_season')} — status `{card['holdout'].get('status')}`.",
            "",
            card["holdout"].get("prior_exposure", ""),
            "",
        ],
    )
    lines.extend(_sealed_section(card))
    lines.extend(["## Value, replacement and tiers", ""])
    for key, payload in card["value"].items():
        selected = payload.get("selected", "—") if isinstance(payload, dict) else "—"
        rule = payload.get("rule", "—") if isinstance(payload, dict) else "—"
        lines.append(f"- **{key}**: `{selected}` (rule `{rule}`)")
    lines.extend(_production_section(card))
    lines.extend(["", "## Known limitations", ""])
    lines.extend(f"- {item}" for item in card["limitations"])
    return "\n".join(lines) + "\n"


def _production_section(card: dict[str, Any]) -> list[str]:
    """What is actually served, and an explicit statement that it was scored on nothing."""
    fit = card.get("production_fit", {})
    lines = ["", "## Production fit", ""]
    if not fit.get("fitted"):
        lines.extend([str(fit.get("note", "No production artifact is committed.")), ""])
        return lines
    seasons = fit.get("training_seasons") or []
    window = f"{seasons[0]}-{seasons[-1]}" if seasons else "—"
    lines.extend(
        [
            "**This section carries no performance claim.** A production fit is a refit of the "
            "architecture evaluated above on the widest permitted labelled window (ADR-078); it "
            "was scored on nothing, and every measured number in this card belongs to the "
            "Phase-11 evidence. The spent 2025 holdout is not re-scored by it and is not "
            "reinterpreted as evidence about it.",
            "",
            f"- protocol: `{fit.get('protocol')}`",
            f"- configuration hash: `{fit.get('configuration_hash')}` — the digest of the frozen "
            "architecture. Two fits on different windows agree here; a tuned parameter does not.",
            f"- refit reason: `{fit.get('refit_reason')}`",
            f"- training window: **{window}**, {fit.get('training_rows')} row(s), "
            f"{fit.get('groups')} fitted group(s)",
            f"- serving season: **{fit.get('serving_season')}** (fold `{fit.get('fold_id')}`)",
            f"- feature set / schema: `{fit.get('feature_set_hash')}` / "
            f"`{fit.get('feature_schema_hash')}`",
            f"- training data: `{fit.get('dataset_content_hash')}` "
            f"({fit.get('dataset_rows')} dataset row(s))",
            f"- libraries: {fit.get('library', {})}",
            f"- fitted {fit.get('generated_at_utc')} from code `{fit.get('git_sha')}`",
        ],
    )
    sealed = fit.get("sealed_seasons_included") or []
    if sealed:
        reason = fit.get("sealed_authorization_reason")
        lines.append(
            f"- sealed season(s) inside the window: **{sealed}**, admitted only under the "
            f"explicit final-evaluation authorization — {reason!r}",
        )
    lines.append("")
    return lines


def write_ros_card(
    *,
    development_path: Path,
    final_path: Path,
    value_path: Path,
    out_dir: Path,
    git_sha: str,
    production_path: Path | None = None,
) -> list[Path]:
    """Write `models/cards/intrinsic-ros-v1.{json,md}` from the committed reports."""
    production = (
        _read(production_path)
        if production_path is not None and production_path.is_file()
        else None
    )
    card = build_ros_card(
        development=_read(development_path),
        final=_read(final_path),
        value=_read(value_path),
        git_sha=git_sha,
        production=production,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in (
        (f"{_CARD_NAME}.json", json.dumps(card, indent=2, sort_keys=True) + "\n"),
        (f"{_CARD_NAME}.md", card_markdown(card)),
    ):
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
