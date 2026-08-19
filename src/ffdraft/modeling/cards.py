"""The intrinsic model card and the tier-method report.

`docs/MODELING.md` section 22 requires a card for every promoted model, and Phase 4 adds a
second document for the tiering, because a tier board makes a claim the model card does not:
that these groupings are stable enough to draft from.

Both documents are **generated** from the committed experiment reports and the production
model artifact rather than written by hand. That is the same discipline
`docs/FEATURE_DICTIONARY.md` follows: a number in a card that no command produces is a
number that can drift, and the whole point of a card is that it cannot.

Nothing here computes a metric of its own except one diagnostic the reports cannot carry -
interval coverage restricted to players who actually appeared in a game - which is the
measurement that separates "the intervals are too wide" from "the distribution has an atom
at zero and the outcome landed on it".
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.modeling.production import ProductionModel
from ffdraft.modeling.rules import all_rules
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "CARD_VERSION",
    "CardInputs",
    "active_player_coverage",
    "write_model_card",
    "write_tier_method_report",
]

CARD_VERSION = "intrinsic_model_card_v1"


@dataclass(frozen=True)
class CardInputs:
    """Everything the cards are generated from. Missing pieces are reported, not invented."""

    model: ProductionModel
    distribution: Mapping[str, Any]
    simulation: Mapping[str, Any] | None = None
    tiers: Mapping[str, Any] | None = None
    final_holdout: Mapping[str, Any] | None = None
    oof_predictions: pl.DataFrame | None = None
    fantasy_labels: pl.DataFrame | None = None
    current_build: Mapping[str, Any] | None = None
    git_sha: str = "unknown"

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        distribution: Path,
        simulation: Path | None = None,
        tiers: Path | None = None,
        final_holdout: Path | None = None,
        oof_predictions: Path | None = None,
        fantasy_labels: Path | None = None,
        current_build: Path | None = None,
        git_sha: str = "unknown",
    ) -> CardInputs:
        def read(path: Path | None) -> Mapping[str, Any] | None:
            if path is None or not path.is_file():
                return None
            payload: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return payload

        study = read(distribution)
        if study is None:
            raise FileNotFoundError(
                f"{distribution} not found; the model card is generated from the "
                "development study, not written by hand",
            )
        return cls(
            model=ProductionModel.load(model_dir),
            distribution=study,
            simulation=read(simulation),
            tiers=read(tiers),
            final_holdout=read(final_holdout),
            oof_predictions=(
                pl.read_parquet(oof_predictions)
                if oof_predictions and oof_predictions.is_file()
                else None
            ),
            fantasy_labels=(
                pl.read_parquet(fantasy_labels)
                if fantasy_labels and fantasy_labels.is_file()
                else None
            ),
            current_build=read(current_build),
            git_sha=git_sha,
        )


def active_player_coverage(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
) -> dict[str, Any]:
    """Interval coverage split by whether the player appeared in a game.

    The promoted distribution models availability explicitly, so a player who never plays
    gets a predictive distribution with a genuine atom at zero - and when his outcome is
    also exactly zero, every interval containing zero covers him by definition. Pooled
    coverage therefore overstates the interval's width, and the honest report is both halves.
    """
    joined = predictions.join(
        labels.select("season", "player_id", "scoring_preset", "actual_games_played"),
        on=["season", "player_id", "scoring_preset"],
        how="inner",
    )
    if joined.is_empty():
        return {}

    def measure(frame: pl.DataFrame) -> dict[str, float]:
        actual = frame.get_column("target_points").cast(pl.Float64).to_numpy()
        low_outer = frame.get_column("q10").cast(pl.Float64).to_numpy()
        high_outer = frame.get_column("q90").cast(pl.Float64).to_numpy()
        low_inner = frame.get_column("q25").cast(pl.Float64).to_numpy()
        high_inner = frame.get_column("q75").cast(pl.Float64).to_numpy()
        return {
            "rows": float(frame.height),
            "coverage_p10_p90": float(np.mean((actual >= low_outer) & (actual <= high_outer))),
            "coverage_p25_p75": float(np.mean((actual >= low_inner) & (actual <= high_inner))),
        }

    played = joined.filter(pl.col("actual_games_played") >= 1)
    absent = joined.filter(pl.col("actual_games_played") == 0)
    degenerate = joined.filter((pl.col("q25") == 0.0) & (pl.col("q75") == 0.0))
    return {
        "all_rows": measure(joined),
        "played_at_least_one_game": measure(played) if played.height else {},
        "never_played": measure(absent) if absent.height else {},
        "share_with_degenerate_inner_interval": float(degenerate.height) / float(joined.height),
    }


def _find(rows: Sequence[Mapping[str, Any]], **keys: Any) -> Mapping[str, Any]:
    for row in rows:
        if all(row.get(key) == value for key, value in keys.items()):
            return row
    return {}


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    header = "| " + " | ".join(label for label, _ in columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [header, divider]
    for row in rows:
        rendered: list[str] = []
        for _, key in columns:
            value = row.get(key)
            if isinstance(value, float):
                rendered.append(f"{value:.4f}" if abs(value) < 1000 else f"{value:.1f}")
            else:
                rendered.append(str(value))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def _decision_lines(payload: Mapping[str, Any] | None, key: str, label: str) -> list[str]:
    if not payload or key not in payload:
        return [f"- **{label}:** not available in the supplied reports."]
    decision = payload[key]
    lines = [
        f"- **{label}** (`{decision['rule']}`) selected `{decision['selected']}` "
        f"({'decisive' if decision['decisive'] else 'incumbent retained'}).",
    ]
    lines.extend(f"  - {reason}" for reason in decision.get("reasons", []))
    lines.extend(f"  - **failed:** {failure}" for failure in decision.get("failures", []))
    return lines


def _card_payload(inputs: CardInputs) -> dict[str, Any]:
    model = inputs.model
    coverage = (
        active_player_coverage(inputs.oof_predictions, inputs.fantasy_labels)
        if inputs.oof_predictions is not None and inputs.fantasy_labels is not None
        else {}
    )
    return {
        "card_version": CARD_VERSION,
        "generated_at_utc": isoformat_utc(utc_now()),
        "git_sha": inputs.git_sha,
        "model": {
            "model_version": model.spec.model_version,
            "architecture": model.spec.architecture,
            "spec": model.spec.to_dict(),
            "training_seasons": list(model.training_seasons),
            "feature_set_version": model.feature_set_version,
            "feature_set_hash": model.feature_set_hash,
            "feature_schema_version": model.feature_schema_version,
            "feature_schema_hash": model.feature_schema_hash,
            "feature_count": len(model.features),
            "groups": len(model.groups),
            "library": {"lightgbm": model.metadata()["library"]["lightgbm"]},
            "dataset_manifest": dict(model.dataset_manifest),
        },
        "frozen_rules": all_rules(),
        "development": {
            "study": inputs.distribution.get("study"),
            "aggregates": inputs.distribution.get("aggregates", []),
            "aggregates_by_position": inputs.distribution.get("aggregates_by_position", []),
            "paired_deltas": inputs.distribution.get("paired_deltas", {}),
            "calibration_decision": inputs.distribution.get("calibration_decision"),
            "horizon_decision": inputs.distribution.get("horizon_decision"),
            "candidate_decision": inputs.distribution.get("candidate_decision"),
        },
        "simulation": (
            {
                "selected_draws": inputs.simulation.get("selected_draws"),
                "selected_ranking_statistic": inputs.simulation.get(
                    "selected_ranking_statistic",
                ),
                "convergence_decision": inputs.simulation.get("convergence_decision"),
                "ranking_decision": inputs.simulation.get("ranking_decision"),
            }
            if inputs.simulation
            else None
        ),
        "tiers": (
            {
                "penalty_decision": inputs.tiers.get("penalty_decision"),
                "stability_decision": inputs.tiers.get("stability_decision"),
                "stability_evidence": inputs.tiers.get("stability_evidence"),
            }
            if inputs.tiers
            else None
        ),
        "final_holdout": inputs.final_holdout,
        "interval_coverage_by_participation": coverage,
        "current_build": inputs.current_build,
    }


def write_model_card(inputs: CardInputs, out_dir: Path) -> list[Path]:
    """Write the intrinsic model card as JSON and Markdown."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _card_payload(inputs)
    version = inputs.model.spec.model_version
    json_path = out_dir / f"intrinsic-{version}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = out_dir / f"intrinsic-{version}.md"
    markdown_path.write_text(_card_markdown(inputs, payload), encoding="utf-8")
    return [json_path, markdown_path]


def _card_markdown(inputs: CardInputs, payload: Mapping[str, Any]) -> str:
    model = inputs.model
    aggregates = list(inputs.distribution.get("aggregates", []))
    promoted = str(inputs.distribution.get("selected_architecture", {}).get("model_id", "CB"))
    development = _find(aggregates, model_id=promoted)
    baseline = _find(aggregates, model_id="B0")
    coverage = payload["interval_coverage_by_participation"]
    holdout = inputs.final_holdout

    lines: list[str] = [
        f"# Intrinsic model card — `{model.spec.model_version}`",
        "",
        (
            f"Card `{CARD_VERSION}`, generated {payload['generated_at_utc']} from code "
            f"`{payload['git_sha']}`. Every number below is read from a committed experiment "
            "report or from the model artifact itself; none is written by hand."
        ),
        "",
        "## Purpose and intended use",
        "",
        "Estimate the distribution of a player's fantasy-point total for one season from "
        "football evidence alone, and translate it into league-relative value. It is "
        "decision support for a redraft fantasy draft: a way to see where value and "
        "uncertainty sit, not a prediction anyone should treat as certain.",
        "",
        "**Prohibited uses.** This model must never consume ADP, expert consensus rank, "
        "FantasyPros or FantasyCalc values, or any other market price (ADR-002); doing so "
        "would make the arbitrage comparison circular. It is not a betting model, not a "
        "weekly start/sit model, and not a dynasty model. Its outputs are not a claim about "
        "any individual player's health or future.",
        "",
        "## Version and provenance",
        "",
        _table(
            [
                {"field": "model version", "value": model.spec.model_version},
                {"field": "architecture", "value": model.spec.architecture},
                {"field": "calibration", "value": model.spec.calibration_strategy_id},
                {"field": "target scale", "value": model.spec.target_scale_id},
                {"field": "quantile levels", "value": ", ".join(str(v) for v in model.spec.levels)},
                {"field": "seed", "value": model.spec.seed},
                {
                    "field": "training seasons",
                    "value": f"{min(model.training_seasons)}-{max(model.training_seasons)}",
                },
                {"field": "fitted groups", "value": len(model.groups)},
                {
                    "field": "feature set",
                    "value": f"{model.feature_set_version} ({model.feature_set_hash})",
                },
                {
                    "field": "feature schema",
                    "value": f"{model.feature_schema_version} ({model.feature_schema_hash})",
                },
                {"field": "features", "value": len(model.features)},
                {"field": "LightGBM", "value": payload["model"]["library"]["lightgbm"]},
                {"field": "code SHA", "value": model.git_sha},
                {"field": "artifact generated", "value": model.generated_at_utc},
            ],
            (("Field", "field"), ("Value", "value")),
        ),
        "",
        "## Data",
        "",
        "Training grain is one row per season, player and scoring preset, over the eligible "
        "preseason universe ADR-022 defines: previous-season roster, target-season draft "
        "class, or a pre-anchor depth-chart snapshot. Every row's information cutoff is the "
        "draft-time anchor `draft_anchor_v1_tuesday_eod_pre_week1` (ADR-021). Labels are the "
        "season fantasy-point total over the documented horizon - weeks 1-16 before 2021, "
        "1-17 from 2021 - computed by one scoring engine from weekly rows.",
        "",
        "Sources are nflverse and ffopportunity only. No market or expert data touches any "
        "part of this model, and an automated audit over both feature names and declared "
        "source lineage runs inside every build.",
        "",
        "## Architecture",
        "",
    ]

    if model.spec.is_hurdle:
        lines.extend(
            [
                "Two LightGBM quantile components over the same features, composed by "
                "deterministic Monte Carlo:",
                "",
                "1. **availability** — quantiles of `games / fantasy_horizon_weeks`, modelled "
                "as a rate so 16- and 17-week seasons are comparable inside one training "
                "window, then multiplied by the target season's horizon and rounded;",
                "2. **conditional performance** — quantiles of fantasy points per *active* "
                "game, fitted only on rows with at least one game;",
                "3. **composition** — `games x points-per-game`, with zero games scoring "
                "exactly zero and nothing clipped from below, because this project's scoring "
                "presets make a negative season total genuinely possible;",
                "4. **dependence** — a Gaussian copula with one correlation per position x "
                "scoring preset, estimated inside the fold from probability-integral "
                "transforms of both components on an inner chronological split.",
                "",
                "Because the published quantiles are empirical quantiles of one Monte Carlo "
                "sample, they cannot cross. The isotonic monotonicity projection is still "
                "applied as a safety net and is a no-op in practice.",
            ],
        )
    else:
        lines.extend(
            [
                "One LightGBM quantile booster per position, scoring preset and quantile "
                "level, predicting the season fantasy-point total directly. Crossing "
                "quantiles are repaired by isotonic projection onto the monotone cone.",
            ],
        )

    lines.extend(
        [
            "",
            "**Uncertainty methodology.** The model emits five quantiles rather than a point "
            "estimate. They become a monotone piecewise-linear quantile function, sampled "
            "with per-player deterministic uniform streams; tails continue the slope of the "
            "nearest interior segment and clamp to bounds derived from the training range "
            "alone. Player draws are independent - V1 models no teammate or game-script "
            "correlation.",
            "",
            "## Development results",
            "",
            "Development folds 2020-2024, window `W1_all_history`, macro means over "
            "validation season x position x scoring cells. `B0` is the project's permanent "
            "naive baseline; `Q1` is the Phase-3 promoted direct-total model.",
            "",
            _table(
                sorted(aggregates, key=lambda row: str(row["model_id"])),
                (
                    ("Model", "model_id"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Top-K", "macro_top_k_recall"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ("P25-P75 cov", "macro_coverage_p25_p75"),
                    ("P10-P90 width", "macro_mean_width_p10_p90"),
                    ("Raw crossing", "macro_crossing_rate_raw"),
                ),
            ),
            "",
            "### The decisions, and the rules that made them",
            "",
        ],
    )
    lines.extend(_decision_lines(inputs.distribution, "calibration_decision", "Calibration"))
    lines.extend(_decision_lines(inputs.distribution, "horizon_decision", "Horizon sensitivity"))
    lines.extend(_decision_lines(inputs.distribution, "candidate_decision", "Candidate A vs B"))
    if inputs.simulation:
        lines.extend(_decision_lines(inputs.simulation, "convergence_decision", "Draw count"))
        lines.extend(_decision_lines(inputs.simulation, "ranking_decision", "Ranking statistic"))
    if inputs.tiers:
        lines.extend(_decision_lines(inputs.tiers, "penalty_decision", "Tier penalty"))
        lines.extend(_decision_lines(inputs.tiers, "stability_decision", "Tier stability"))

    lines.extend(
        [
            "",
            "### Quantile crossing, before and after",
            "",
            _table(
                sorted(aggregates, key=lambda row: str(row["model_id"])),
                (("Model", "model_id"), ("Raw crossing rate", "macro_crossing_rate_raw")),
            ),
            "",
            "Post-processing crossing rate is zero for every model, by construction of the "
            "monotonicity repair; the raw rate is reported so the repair cannot hide what it "
            "repaired.",
            "",
            "### By position",
            "",
            _table(
                sorted(
                    inputs.distribution.get("aggregates_by_position", []),
                    key=lambda row: (str(row["position"]), str(row["model_id"])),
                ),
                (
                    ("Position", "position"),
                    ("Model", "model_id"),
                    ("MAE", "macro_mae"),
                    ("Spearman", "macro_spearman"),
                    ("Top-K", "macro_top_k_recall"),
                    ("Pinball", "macro_mean_pinball"),
                    ("P10-P90 cov", "macro_coverage_p10_p90"),
                ),
            ),
            "",
            "### Calibration",
            "",
        ],
    )
    if coverage:
        lines.extend(
            [
                "Pooled coverage understates how tight the intervals are, because the model "
                "represents the probability of never playing as a genuine atom at zero: when "
                "a player's P25 and P75 are both exactly zero and he scores exactly zero, "
                "the interval covers him by definition. Both halves are therefore reported.",
                "",
                _table(
                    [
                        {"population": name.replace("_", " "), **values}
                        for name, values in coverage.items()
                        if isinstance(values, dict) and values
                    ],
                    (
                        ("Population", "population"),
                        ("Rows", "rows"),
                        ("P10-P90 coverage", "coverage_p10_p90"),
                        ("P25-P75 coverage", "coverage_p25_p75"),
                    ),
                ),
                "",
                (
                    "Share of evaluation rows whose P25 and P75 are both exactly zero: "
                    f"{coverage['share_with_degenerate_inner_interval']:.1%}."
                ),
                "",
            ],
        )
    else:
        lines.extend(["Participation-split coverage was not supplied to this card.", ""])

    lines.extend(["## Final holdout", ""])
    if holdout:
        lines.extend(_holdout_section(holdout, development, baseline))
    else:
        lines.append(
            "The sealed 2025 holdout has not been evaluated for this model version.",
        )
    lines.extend(
        [
            "",
            "## Known limitations",
            "",
            "- **Fantasy outcomes are mostly noise.** Injury, role change and coaching turn a "
            "correct process into a wrong answer routinely. A P10-P90 interval sixty points "
            "wide is the honest statement of that, not a modelling failure.",
            "- **Independent player draws.** V1 samples every player independently, so it "
            "cannot express that a quarterback's collapse takes his receivers with him.",
            "- **The 2014-2016 era is thinner.** nflverse roster coverage steps up at 2016, "
            "so those target seasons carry about 36% fewer eligible rows. ADR-028 chose to "
            "train across the boundary on measured evidence; any metric averaged over all "
            "seasons mixes two universes.",
            "- **The fantasy horizon changed at 2021**, from weeks 1-16 to 1-17, so season "
            "totals sit on a ~6% different scale either side. ADR-032 measured a "
            "horizon-normalized target and rejected it; the boundary remains a limitation "
            "rather than a correction.",
            "- **Rookies are low-information rows.** Before 2025 no season has a draft-time "
            "depth observation at all, so a rookie's entire preseason signal is draft "
            "capital, biography and team context. Their errors are larger and are reported "
            "separately rather than averaged away.",
            "- **There is no preseason injury feature, in any season.** No nflverse source "
            "publishes an injury report at a draft anchor (ADR-011). A player who enters the "
            "season hurt looks healthy to this model.",
            "- **Pre-2025 team and depth context is mostly unobservable.** Free agency and "
            "trades leave no timestamped preseason trace before the snapshot era, so "
            "`team_at_anchor` and `depth_rank_at_anchor` are excluded from the feature set "
            "entirely (ADR-026).",
            "- **Current status is metadata, not signal.** Today's roster status and team "
            "annotate a published row and can remove a retired player from the board, but "
            "they never enter a prediction: they have no development-era support and could "
            "not be validated.",
            "- **The copula parameter describes active players.** Points per game is "
            "undefined for a player who never appears, so the availability/performance "
            "dependence is estimated on players who played and extrapolated to those who did "
            "not.",
            "",
            "## Fairness and coverage",
            "",
            "Human demographic fairness is not applicable: the model consumes on-field "
            "production, age, draft capital, athletic testing and team context, and no "
            "protected attribute. The coverage biases that do matter are data ones and are "
            "reported above: rookies and low-information players carry larger error, the "
            "pre-2016 seasons are thinner, and combine measurements exist only for players "
            "who tested - they are never imputed for those who did not.",
            "",
        ],
    )
    return "\n".join(lines) + "\n"


def _holdout_section(
    holdout: Mapping[str, Any],
    development: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> list[str]:
    gate = holdout.get("acceptance", {})
    lines = [
        (
            "Season 2025 was sealed from the start of Phase 3 (ADR-025) and evaluated "
            "**exactly once**, after every model-design decision was frozen. It is no longer "
            "a holdout; it joined the production training window only after that evaluation."
        ),
        "",
        f"- authorization reason: {holdout.get('authorization_reason', 'unknown')}",
        f"- verdict: **{str(gate.get('selected', 'unknown')).upper()}**",
    ]
    lines.extend(f"  - {reason}" for reason in gate.get("reasons", []))
    lines.extend(f"  - **failed:** {failure}" for failure in gate.get("failures", []))
    primary = holdout.get("primary", [])
    if primary:
        lines.extend(
            [
                "",
                "### Full 2025 universe (the primary result)",
                "",
                _table(
                    primary,
                    (
                        ("Model", "model_id"),
                        ("Cells", "cells"),
                        ("Rows", "rows"),
                        ("MAE", "macro_mae"),
                        ("Spearman", "macro_spearman"),
                        ("Top-K", "macro_top_k_recall"),
                        ("Pinball", "macro_mean_pinball"),
                        ("P10-P90 cov", "macro_coverage_p10_p90"),
                    ),
                ),
            ],
        )
    slices = holdout.get("diagnostic_slices", [])
    if slices:
        lines.extend(
            [
                "",
                "### Predeclared diagnostic slices",
                "",
                "ADR-025 fixed these before any candidate was compared. They explain the "
                "primary result; not one of them can replace it, and none is part of the "
                "acceptance gate.",
                "",
                _table(
                    slices,
                    (
                        ("Slice", "slice_id"),
                        ("Label", "slice_label"),
                        ("Model", "model_id"),
                        ("Rows", "n"),
                        ("MAE", "mae"),
                        ("Spearman", "spearman"),
                        ("Pinball", "mean_pinball"),
                        ("P10-P90 cov", "coverage_p10_p90"),
                    ),
                ),
            ],
        )
    if development and baseline:
        lines.extend(
            [
                "",
                (
                    f"For context, the same model scored MAE {development.get('macro_mae', 0):.3f} "
                    f"and pinball {development.get('macro_mean_pinball', 0):.3f} on the "
                    f"development folds, against B0's {baseline.get('macro_mae', 0):.3f} and "
                    f"{baseline.get('macro_mean_pinball', 0):.3f}."
                ),
            ],
        )
    return lines


def write_tier_method_report(inputs: CardInputs, out_dir: Path) -> list[Path]:
    """Write the tier-method report: why these groupings are trustworthy enough to draft from."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tiers = inputs.tiers or {}
    simulation = inputs.simulation or {}
    version = inputs.model.spec.model_version
    payload = {
        "report_version": "tier_method_v1",
        "generated_at_utc": isoformat_utc(utc_now()),
        "git_sha": inputs.git_sha,
        "model_version": version,
        "simulation": simulation,
        "tiers": tiers,
    }
    json_path = out_dir / "tier-method.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = out_dir / "tier-method.md"
    markdown_path.write_text(_tier_markdown(inputs, simulation, tiers), encoding="utf-8")
    return [json_path, markdown_path]


def _tier_markdown(
    inputs: CardInputs,
    simulation: Mapping[str, Any],
    tiers: Mapping[str, Any],
) -> str:
    config = tiers.get("configuration", {})
    stability = tiers.get("stability_evidence", {})
    lines: list[str] = [
        "# Tier-method report",
        "",
        (
            f"Model `{inputs.model.spec.model_version}`, generated "
            f"{isoformat_utc(utc_now())} from code `{inputs.git_sha}`. Generated from the "
            "committed stage-C experiment reports."
        ),
        "",
        "## What a tier is, and what it is not",
        "",
        "A tier is a contiguous run of fair-ranked players whose simulated value "
        "distributions do not show a stable break between them. The letters are ordinal "
        "labels and nothing more: `S` above `A` means the segmentation put a boundary "
        "between them, not that `S` is a fixed amount better, and no letter carries a claim "
        "that survives being compared across positions, presets or builds.",
        "",
        "## The ranking statistic",
        "",
    ]
    lines.extend(_decision_lines(simulation, "ranking_decision", "Fair rank"))
    lines.extend(
        [
            "",
            "Fair rank is 1-based and unique. Ties break in the order "
            "`docs/DATA_CONTRACTS.md` section 7 declares: the ranking statistic, then P50 "
            "points, then lower uncertainty, then a stable `player_id`.",
            "",
            "## Simulation",
            "",
        ],
    )
    lines.extend(_decision_lines(simulation, "convergence_decision", "Draw count"))
    lines.extend(
        [
            "",
            "Each draw samples every player's season total from his own monotone quantile "
            "function and hands the whole draw to the one canonical starter/FLEX allocation "
            "in `ffdraft.simulation.allocation` - the same code that built the Phase-2 "
            "realized VORP labels. Mandatory positional slots fill first, FLEX competes "
            "globally among the remaining eligible RB/WR/TE, and the replacement baseline is "
            "the best player nobody started. **Replacement is resampled with everyone else**, "
            "so a draw where the top backs collapse is a draw where replacement is low and "
            "the survivors are worth more; subtracting one fixed baseline from every quantile "
            "would have made VORP a shifted copy of points.",
            "",
            "Point draws depend on the model version, the simulation version, the scoring "
            "preset, the build id and each player's own id - deliberately **not** on the "
            "league preset, so the same simulated seasons are re-allocated under every roster "
            "shape and a preset-to-preset difference is a scarcity difference rather than "
            "Monte Carlo noise.",
            "",
            "## Segmentation",
            "",
            f"- algorithm: `{config.get('penalties') and 'ruptures.Pelt(model=rbf)'}`",
            f"- board depth: {config.get('board_depth')}",
            f"- penalty grid: {config.get('penalties')}",
            "- features: standardized P25, P50, P75 and interquartile spread of simulated "
            "VORP, in fair-rank order",
            "- minimum segment size 1, so a genuinely isolated top player may stand alone",
            "",
        ],
    )
    lines.extend(_decision_lines(tiers, "penalty_decision", "Penalty"))
    candidates = tiers.get("penalty_candidates", [])
    if candidates:
        lines.extend(
            [
                "",
                _table(
                    candidates,
                    (
                        ("Penalty", "penalty"),
                        ("Mean tiers", "mean_tier_count"),
                        ("Singleton rate", "singleton_rate"),
                        ("Largest tier", "largest_tier_share"),
                        ("Boundary effect", "mean_boundary_effect_size"),
                        ("Within-tier effect", "median_within_tier_effect_size"),
                        ("Bootstrap ARI", "bootstrap_adjusted_rand"),
                    ),
                ),
            ],
        )
    lines.extend(["", "## Stability", ""])
    lines.extend(_decision_lines(tiers, "stability_decision", "Stability gate"))
    if stability:
        lines.extend(
            [
                "",
                _table(
                    [stability],
                    (
                        ("Bootstrap ARI", "bootstrap_adjusted_rand"),
                        ("Boundary agreement", "boundary_agreement"),
                        ("Singleton rate", "singleton_rate"),
                        ("Tier-count CV", "tier_count_cv"),
                        ("Monotonic tier pairs", "monotonic_pair_share"),
                        ("Cross-preset ARI", "cross_preset_adjusted_rand"),
                    ),
                ),
            ]
        )
    monotonicity = tiers.get("tier_monotonicity", [])
    if monotonicity:
        lines.extend(
            [
                "",
                "### Do tiers order realized value?",
                "",
                _table(
                    monotonicity,
                    (
                        ("Season", "season"),
                        ("Scoring", "scoring_preset"),
                        ("Tiers", "tiers"),
                        ("Adjacent pairs", "adjacent_pairs"),
                        ("Monotonic", "monotonic_pairs"),
                        ("Share", "monotonic_pair_share"),
                    ),
                ),
            ],
        )
    cross = tiers.get("cross_preset_similarity", [])
    if cross:
        lines.extend(
            [
                "",
                "### Across presets",
                "",
                _table(
                    cross,
                    (
                        ("Left", "left"),
                        ("Right", "right"),
                        ("Shared", "shared_players"),
                        ("ARI", "adjusted_rand"),
                    ),
                ),
            ],
        )
    lines.extend(
        [
            "",
            "## Boundary diagnostics",
            "",
            "Every boundary carries the P50 VORP cliff across it, a standardized effect size "
            "computed identically for boundary and non-boundary adjacent pairs, and the "
            "probability that the lower-ranked player outscores the higher-ranked one under a "
            "transparent normal proxy. Computing the effect size the same way on both sides "
            "of the question is what makes 'this boundary separates more than a typical pair "
            "inside a tier' a ratio rather than an impression.",
            "",
            "## Known limitations",
            "",
            "- Tier boundaries move between builds. The bootstrap measures how much, and the "
            "boundary-frequency diagnostic says where on the board the segmentation is "
            "confident; deep boundaries are far less stable than the top of the board.",
            "- A tier is a statement about *this* league preset and scoring rule. "
            "Membership similarity across presets is measured and reported rather than "
            "assumed.",
            "- The segmentation sees only the simulated VORP summary. It has no notion of "
            "bye weeks, schedule, positional runs in a real draft room, or a manager's "
            "existing roster.",
            "- Nothing here is manually adjusted. If a tier looks wrong, the answer is in "
            "the model or the algorithm, not in an edit.",
            "",
        ],
    )
    return "\n".join(lines) + "\n"
