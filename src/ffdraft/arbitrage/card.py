"""The arbitrage method card, generated from the evidence that produced the board.

Same rule as the model card and the feature dictionary: **a number in a card that no command
produces is a number that can drift.** Everything here is read from the artifacts, the
committed cohort report and the frozen constants — nothing is hand-copied, so regenerating
after a rebuild is the whole maintenance story.

The card exists to answer, for a reader who did not write the code: what is this score, why
is there no model behind it, where did the price come from, how stale is it, what does
`confidence` mean, and what would have to be true before any of this became machine learning.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ffdraft.arbitrage.baseline import SCORE_MAXIMUM, SCORE_MINIMUM
from ffdraft.arbitrage.confidence import CONFIDENCE_RUBRIC
from ffdraft.arbitrage.frozen import (
    ARBITRAGE_METHOD_VERSION,
    ARBITRAGE_ML_HISTORICAL_FEASIBLE,
    ARBITRAGE_MODE,
    ARBITRAGE_REVISIT_SNAPSHOT_SEASONS,
    FAIR_RANK_STATISTIC,
)
from ffdraft.market.cohorts import COHORT_SUFFICIENCY_RULE
from ffdraft.market.trend import TREND_RULE
from ffdraft.timeutil import utc_now

__all__ = ["ARBITRAGE_CARD_NAME", "build_card", "card_markdown", "write_arbitrage_card"]

ARBITRAGE_CARD_NAME = "arbitrage-method-a0"


def _read(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def build_card(
    *,
    artifacts_dir: Path,
    selection_path: Path | None,
    git_sha: str = "unknown",
) -> dict[str, Any]:
    """Assemble the machine-readable card from the artifacts and the cohort report."""
    arbitrage = _read(artifacts_dir / "arbitrage.json")
    metadata = _read(artifacts_dir / "build_metadata.json")
    selection = _read(selection_path) if selection_path and selection_path.is_file() else {}
    records = list(arbitrage.get("records", ()))

    confidence = Counter(str(record.get("confidence")) for record in records)
    flags = Counter(flag for record in records for flag in record.get("quality_flags", ()))
    presets = sorted(
        {(str(record["league_preset_id"]), str(record["scoring_preset"])) for record in records},
    )
    market = dict(metadata.get("market") or {})

    return {
        "card_version": "1.0",
        "generated_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "git_sha": git_sha,
        "method": {
            "name": "A0 — fair rank versus ADP",
            "version": ARBITRAGE_METHOD_VERSION,
            "mode": str(ARBITRAGE_MODE),
            "learned_model": None,
            "ml_historical_feasible": ARBITRAGE_ML_HISTORICAL_FEASIBLE,
            "rank_gap": "market_adp - fair_rank; positive = model would take him earlier",
            "regional_value_gap": "ln(market_adp / fair_rank); 0 = agreement",
            "arbitrage_score": (
                f"midpoint percentile of regional_value_gap within one (league preset, "
                f"scoring preset) block, {SCORE_MINIMUM:.0f}-{SCORE_MAXIMUM:.0f}; ties "
                "share the mean of their group's percentiles"
            ),
            "reliability_adjustment": None,
            "fair_rank_source": {
                "artifact": "tiers.json",
                "statistic": FAIR_RANK_STATISTIC,
                "intrinsic_model_version": metadata.get("intrinsic_model_version"),
                "uses_tier_boundaries": False,
            },
        },
        "market_source": {
            "source_id": market.get("source_id"),
            "snapshot_key": market.get("snapshot_key"),
            "snapshot_at_utc": market.get("snapshot_at_utc"),
            "source_as_of_utc": None,
            "source_as_of_note": (
                "MyFantasyLeague publishes no data-as-of time; its response timestamp is "
                "generation time and is retained as vendor metadata only"
            ),
            "adp_sd": None,
            "adp_sd_note": (
                "MyFantasyLeague publishes no standard deviation; dispersion is min/max pick"
            ),
            "retention": {
                "mechanism": "dedicated long-lived `market-data` git branch, append-only",
                "layout": "market/<source>/<season>/<YYYY-MM-DDTHH-MM-SSZ>/",
                "decision": "ADR-038",
            },
        },
        "cohort_policy": {
            "rule_version": selection.get("rule_version"),
            "rule": COHORT_SUFFICIENCY_RULE.to_dict(),
            "measured_from_snapshot": selection.get("snapshot_key"),
            "assignments": market.get("assignments", []),
            "half_ppr_note": (
                "MFL exposes IS_PPR as a boolean and publishes no half-PPR filter, so a "
                "HALF assignment is never exact (ADR-039)"
            ),
        },
        "confidence": CONFIDENCE_RUBRIC.to_dict(),
        "trend": {
            **TREND_RULE.to_dict(),
            "available": bool(market.get("trend_available", False)),
            "history_snapshots": market.get("trend_history_snapshots", 0),
            "source": "our own retained point-in-time snapshots only, never MFL history",
        },
        "coverage": market.get("coverage", {}),
        "identity": {
            "policy": "namespaced canonical ids, two independent bridges, fail closed (ADR-019)",
            "name_matching": "never resolves a production record",
            "unpriced_top_players": market.get("unpriced_top_players", 0),
        },
        "board": {
            "build_id": arbitrage.get("build_id"),
            "records": len(records),
            "presets": [
                {"league_preset_id": preset, "scoring_preset": scoring}
                for preset, scoring in presets
            ],
            "confidence_counts": dict(sorted(confidence.items())),
            "quality_flag_counts": dict(sorted(flags.items())),
        },
        "limitations": [
            "No learned model. expected_surplus_vorp and p_positive_surplus are null on "
            "every row and are not approximated (ADR-010).",
            "Cohorts are approximate wherever the source cannot express a preset; HALF always is.",
            "adp_low/adp_high are extreme order statistics that widen with sample size, so "
            "they describe dispersion but do not move confidence (ADR-041).",
            "market_trend is null until at least three observation days spanning three days "
            "exist in the retained store (ADR-042).",
            "The intrinsic fair rank this compares against carries its own published "
            "limitations: the Monte Carlo convergence rule fell through to its fallback "
            "(ADR-034) and the tier stability gate failed (ADR-035). A0 uses fair rank, not "
            "tier boundaries, so the second does not propagate into this score.",
        ],
        "degraded_behaviour": {
            "market_unavailable": "no arbitrage artifact; the Tier board is unaffected",
            "stale_snapshot": (
                "every row flagged market_snapshot_stale and capped at low confidence"
            ),
            "player_unpriced": "no arbitrage row; the player keeps his tier row",
        },
        "revisit_condition": {
            "learned_arbitrage": (
                f"at least {ARBITRAGE_REVISIT_SNAPSHOT_SEASONS} draft seasons of our own "
                "point-in-time snapshots, then an out-of-time promotion gate against A0"
            ),
            "decision": "ADR-010",
        },
        "licensing": {
            "market": (
                "MyFantasyLeague developer rules: free use, registered client User-Agent "
                "transmitted, player database requested at most once per day, 429 backed off"
            ),
            "attribution": "MyFantasyLeague ADP export; Sleeper (non-commercial) for status",
            "decisions": ["ADR-017", "ADR-013", "ADR-016"],
        },
    }


def _trend_state(trend: dict[str, Any]) -> str:
    if trend.get("available"):
        return "**available**"
    return (
        "**null on every row** — the retained store does not yet hold enough history, "
        "which is the correct output rather than a gap to fill"
    )


def card_markdown(card: dict[str, Any]) -> str:
    """Render the human-readable half. Generated; do not hand-edit."""
    method = card["method"]
    market = card["market_source"]
    cohort = card["cohort_policy"]
    board = card["board"]
    trend = card["trend"]

    lines = [
        "# Arbitrage method card — A0, fair rank versus ADP",
        "",
        f"**Version** `{method['version']}` · **mode** `{method['mode']}` · "
        f"**generated** {card['generated_at_utc']} · **code** `{card['git_sha']}`",
        "",
        "## Why there is no model here",
        "",
        "MyFantasyLeague's historical ADP export is a season-long aggregate recomputed at "
        'request time, and its day-window filter is ignored. A historical "market cost" '
        "therefore includes drafts held after the season's outcomes were partly known — "
        "which would contaminate exactly the signal a learned arbitrage model exists to "
        "exploit. So V1 computes a transparent baseline and calls it one (ADR-010).",
        "",
        f"`expected_surplus_vorp` and `p_positive_surplus` are null on all "
        f"{board['records']} rows. They are not approximated, and no output is labelled "
        "`ml`.",
        "",
        f"**Revisit condition.** {card['revisit_condition']['learned_arbitrage']}.",
        "",
        "## The formula",
        "",
        "```text",
        "rank_gap           = market_adp - fair_rank",
        "regional_value_gap = ln(market_adp / fair_rank)",
        "arbitrage_score    = midpoint percentile of regional_value_gap, within preset",
        "```",
        "",
        "Positive `rank_gap` means the model would take the player **earlier** than the "
        "market does — a bargain. Zero is agreement. Negative means the market is paying up.",
        "",
        "The log ratio exists because the same absolute gap means different things in "
        "different regions of a draft: eight picks between fair rank 3 and ADP 11 is a round "
        "of value; eight picks between 180 and 188 is noise.",
        "",
        f"Fair rank comes from `{method['fair_rank_source']['statistic']}` in "
        f"`{method['fair_rank_source']['artifact']}`, produced by "
        f"`{method['fair_rank_source']['intrinsic_model_version']}`. Tier ordinals and tier "
        "edges are **not** inputs.",
        "",
        "## Market source",
        "",
        f"- source `{market['source_id']}`, snapshot `{market['snapshot_key']}` retrieved "
        f"{market['snapshot_at_utc']}",
        f"- retained on the {market['retention']['mechanism']} at "
        f"`{market['retention']['layout']}`",
        f"- `source_as_of_utc` is null: {market['source_as_of_note']}",
        f"- `market_adp_sd` is null: {market['adp_sd_note']}",
        "",
        "## Cohort selection",
        "",
        f"Rule `{cohort['rule_version']}`, frozen before the measurement that applied it. "
        f"Measured against retained snapshot `{cohort['measured_from_snapshot']}`.",
        "",
        "| scoring | teams | cohort | exact | sufficient |",
        "|---|---:|---|---|---|",
    ]
    for assignment in cohort.get("assignments", []):
        lines.append(
            f"| {assignment['scoring_preset']} | {assignment['league_size']} | "
            f"`{assignment['cohort_id']}` | {'yes' if assignment['exact'] else 'no'} | "
            f"{'yes' if assignment['sufficient'] else 'no'} |",
        )
    lines += [
        "",
        cohort["half_ppr_note"] + ".",
        "",
        "## Confidence",
        "",
        "`confidence` is a statement about **market-data quality**, not a probability. "
        f"Rubric `{card['confidence']['rubric_version']}`:",
        "",
        f"- **unknown** — {card['confidence']['unknown']}",
        f"- **low** — {card['confidence']['low']}",
        f"- **medium** — {card['confidence']['medium']}",
        f"- **high** — {card['confidence']['high']}",
        "",
        "Dispersion is excluded from the tiers because "
        f"{card['confidence']['dispersion_excluded_because']}.",
        "",
        f"Observed on this board: {board['confidence_counts']}.",
        "",
        "## Trend",
        "",
        f"`market_trend` is the {trend['statistic']} over a {trend['window_days']:.0f}-day "
        f"window, requiring at least {trend['min_observation_days']} observation days "
        f"spanning {trend['min_span_days']:.0f} days. {trend['sign_convention']}.",
        "",
        f"Source: {trend['source']}. Currently {_trend_state(trend)} "
        f"({trend['history_snapshots']} snapshot(s) in window).",
        "",
        "## Coverage and flags",
        "",
        f"- records: {board['records']} across {len(board['presets'])} preset block(s)",
        f"- quality flags: {board['quality_flag_counts']}",
        f"- top-150 board players with no price: {card['identity']['unpriced_top_players']}",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in card["limitations"])
    lines += [
        "",
        "## Degraded behaviour",
        "",
    ]
    lines.extend(f"- **{key}** — {value}" for key, value in card["degraded_behaviour"].items())
    lines += [
        "",
        "## Licensing and attribution",
        "",
        f"- {card['licensing']['market']}",
        f"- attribution: {card['licensing']['attribution']}",
        f"- decisions: {', '.join(card['licensing']['decisions'])}",
        "",
    ]
    return "\n".join(lines)


def write_arbitrage_card(
    *,
    artifacts_dir: Path,
    selection_path: Path | None,
    out_dir: Path,
    git_sha: str = "unknown",
) -> list[Path]:
    """Write ``arbitrage-method-a0.json`` and ``.md``."""
    card = build_card(
        artifacts_dir=artifacts_dir,
        selection_path=selection_path,
        git_sha=git_sha,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{ARBITRAGE_CARD_NAME}.json"
    md_path = out_dir / f"{ARBITRAGE_CARD_NAME}.md"
    json_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(card_markdown(card), encoding="utf-8")
    return [json_path, md_path]
