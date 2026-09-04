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
from ffdraft.ros.gate import ROS_PROMOTION_CRITERIA
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
) -> dict[str, Any]:
    """Assemble the machine-readable card from the committed reports."""
    selection = ros_feature_selection()
    gate = development.get("gate", {})
    macro = development.get("macro_by_model", {})
    return {
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
        "limitations": _limitations(),
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
        "Nothing here is published. Phase 11 is an offline subsystem; exposing it safely is "
        "Phase 12's job.",
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
    lines = [
        f"# Rest-of-season model card — `{card['model_version']}`",
        "",
        f"Card `{card['card_version']}`, generated {card['generated_at_utc']} from code "
        f"`{card['git_sha']}`. Every number below is read from a committed report or from the "
        "code's own frozen declarations; none is written by hand.",
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
            "## Promotion decision",
            "",
            f"Rule `{card['promotion']['criteria']['criteria_version']}` — "
            f"**{'PROMOTED' if decision.get('promoted') else 'NOT PROMOTED'}**.",
            "",
        ],
    )
    for reason in decision.get("satisfied_clauses", []):
        lines.append(f"- satisfied: {reason}")
    for reason in decision.get("failed_clauses", []):
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
    lines.extend(["", "## Known limitations", ""])
    lines.extend(f"- {item}" for item in card["limitations"])
    return "\n".join(lines) + "\n"


def write_ros_card(
    *,
    development_path: Path,
    final_path: Path,
    value_path: Path,
    out_dir: Path,
    git_sha: str,
) -> list[Path]:
    """Write `models/cards/intrinsic-ros-v1.{json,md}` from the committed reports."""
    card = build_ros_card(
        development=_read(development_path),
        final=_read(final_path),
        value=_read(value_path),
        git_sha=git_sha,
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
