"""Phase 4, stage C: choosing and testing the tier segmentation.

Two frozen rules decide, both from ADR-030:

``phase4_tier_v1``
    which penalty from the fixed six-value grid is promoted. Admissibility comes first and
    is scale-free where it can be - enough tiers to be a tiering, few enough to read, no
    singleton proliferation, no tier swallowing the board, and boundaries that separate
    players more than a typical adjacent pair *inside* a tier does. Only among admissible
    penalties does stability choose.

``phase4_tier_stability_v1``
    whether the promoted segmentation is steady enough to put in front of a drafter.

The resampling unit is the simulated season, not the player: tiers are a function of the
Monte Carlo VORP distribution, so the honest question is how much of the board is a property
of the model rather than of these particular draws. Each replicate re-ranks *and*
re-segments, because the fair ranks come from the same draws and holding them fixed would
flatter every boundary.

Everything runs on development folds under the draw count and ranking statistic the
simulation study already chose. Nothing here can see the sealed season.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ffdraft.config import LeagueConfig
from ffdraft.contracts import CheckStatus, QualityCheck
from ffdraft.modeling.folds import DEFAULT_SEED, DEVELOPMENT_VALIDATION_SEASONS
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.modeling.rules import (
    TIER_BOARD_DEPTH,
    TIER_PENALTY_GRID,
    TIER_SELECTION,
    TIER_STABILITY_GATE,
    Decision,
    TierCandidateEvidence,
    TierStabilityEvidence,
    evaluate_tier_stability,
    select_tier_penalty,
)
from ffdraft.simulation.study import (
    OOF_QUANTILE_COLUMNS,
    DevelopmentScenario,
    training_bounds,
)
from ffdraft.simulation.vorp import SimulationConfig, fair_ranking, sample_points, simulate_vorp
from ffdraft.tiers.labels import tier_label
from ffdraft.tiers.segmentation import Segmentation, segment_board
from ffdraft.tiers.stability import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    adjusted_rand_index,
    bootstrap_stability,
)
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "TIER_STUDY_VERSION",
    "TierStudyConfig",
    "TierStudyResult",
    "run_tier_study",
    "write_tier_report",
]

TIER_STUDY_VERSION = "phase4_tiers_v1"

_DEFAULT_LEAGUE = "redraft-12"


@dataclass(frozen=True)
class TierStudyConfig:
    """Everything the tier study is a function of."""

    draws: int
    statistic: str
    seed: int = DEFAULT_SEED
    board_depth: int = TIER_BOARD_DEPTH
    penalties: tuple[float, ...] = TIER_PENALTY_GRID
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES
    #: Every development season under the default league preset. Broad evidence for the
    #: shape diagnostics, which are cheap.
    seasons: tuple[int, ...] = DEVELOPMENT_VALIDATION_SEASONS
    scoring_presets: tuple[str, ...] = ("STD", "HALF", "PPR")
    #: A declared subset for the bootstrap, which is not cheap. Two seasons at opposite ends
    #: of the development range, all three scoring presets.
    bootstrap_seasons: tuple[int, ...] = (2022, 2024)
    #: The season whose boards are compared across league sizes and scoring presets.
    preset_comparison_season: int = 2024
    league_presets: tuple[str, ...] = ("redraft-10", "redraft-12", "redraft-14")
    levels: tuple[float, ...] = QUANTILE_LEVELS
    model_version: str = "phase4_development"

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_version": TIER_STUDY_VERSION,
            "draws": self.draws,
            "statistic": self.statistic,
            "seed": self.seed,
            "board_depth": self.board_depth,
            "penalties": list(self.penalties),
            "bootstrap_replicates": self.bootstrap_replicates,
            "seasons": list(self.seasons),
            "scoring_presets": list(self.scoring_presets),
            "bootstrap_seasons": list(self.bootstrap_seasons),
            "preset_comparison_season": self.preset_comparison_season,
            "league_presets": list(self.league_presets),
            "default_league_preset": _DEFAULT_LEAGUE,
        }

    def scenarios(self) -> list[DevelopmentScenario]:
        return [
            DevelopmentScenario(season, scoring, _DEFAULT_LEAGUE)
            for season in self.seasons
            for scoring in self.scoring_presets
        ]

    def preset_scenarios(self) -> list[DevelopmentScenario]:
        return [
            DevelopmentScenario(self.preset_comparison_season, scoring, preset)
            for scoring in self.scoring_presets
            for preset in self.league_presets
        ]


@dataclass
class TierStudyResult:
    """Everything the tier study produced."""

    config: TierStudyConfig
    boards: list[dict[str, Any]]
    penalty_candidates: list[dict[str, Any]]
    penalty_decision: Decision
    stability_by_penalty: dict[str, dict[str, Any]]
    stability_decision: Decision
    stability_evidence: dict[str, Any]
    boundary_diagnostics: list[dict[str, Any]]
    monotonicity: list[dict[str, Any]]
    cross_preset: list[dict[str, Any]]
    example_board: list[dict[str, Any]]
    checks: list[QualityCheck] = field(default_factory=list)
    runtime_seconds: float = 0.0

    @property
    def penalty(self) -> float:
        return float(self.penalty_decision.selected)

    @property
    def passed(self) -> bool:
        return all(not check.blocking for check in self.checks)


def _simulate_board(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    league: LeagueConfig,
    scenario: DevelopmentScenario,
    config: TierStudyConfig,
    *,
    keep_draws: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, Any]:
    """Simulate one scenario and return (full player summary, ranked board, result)."""
    projections = predictions.filter(
        (pl.col("season") == scenario.season)
        & (pl.col("scoring_preset") == scenario.scoring_preset),
    ).sort("player_id")
    bounds = training_bounds(
        modelling_frame,
        season=scenario.season,
        scoring_preset=scenario.scoring_preset,
    )
    simulation_config = SimulationConfig(
        draws=config.draws,
        seed=config.seed,
        model_version=config.model_version,
        scoring_preset=scenario.scoring_preset,
        build_id=f"development:{scenario.season}",
        levels=config.levels,
    )
    sampled = sample_points(
        projections,
        config=simulation_config,
        bounds=bounds,
        quantile_columns=OOF_QUANTILE_COLUMNS,
    )
    result = simulate_vorp(
        projections,
        preset=league.preset(scenario.league_preset_id),
        config=simulation_config,
        bounds=bounds,
        points=sampled,
        keep_draws=keep_draws,
    )
    ranked = fair_ranking(result.players, statistic=config.statistic).head(config.board_depth)
    return result.players, ranked, result


def _candidate_evidence(
    shape: Sequence[Mapping[str, Any]],
    stability: Mapping[float, Any],
    penalties: Sequence[float],
) -> list[TierCandidateEvidence]:
    evidence: list[TierCandidateEvidence] = []
    for penalty in penalties:
        rows = [row for row in shape if float(row["penalty"]) == float(penalty)]
        if not rows:
            continue
        report = stability.get(penalty)
        evidence.append(
            TierCandidateEvidence(
                penalty=float(penalty),
                mean_tier_count=float(np.mean([row["tier_count"] for row in rows])),
                singleton_rate=float(np.mean([row["singleton_rate"] for row in rows])),
                largest_tier_share=float(np.mean([row["largest_tier_share"] for row in rows])),
                mean_boundary_effect_size=float(
                    np.nanmean([row["mean_boundary_effect_size"] for row in rows]),
                ),
                median_within_tier_effect_size=float(
                    np.nanmean([row["median_within_tier_effect_size"] for row in rows]),
                ),
                bootstrap_adjusted_rand=(
                    float(report.adjusted_rand) if report is not None else float("nan")
                ),
                boundary_agreement=(
                    float(report.boundary_agreement) if report is not None else float("nan")
                ),
            ),
        )
    return evidence


def _monotonicity(
    ranked: pl.DataFrame,
    segmentation: Segmentation,
    realized: pl.DataFrame,
    scenario: DevelopmentScenario,
) -> dict[str, Any]:
    """Does realized VORP fall as the tier ordinal grows?"""
    board = ranked.with_columns(
        pl.Series("tier_ordinal", list(segmentation.ordinals), dtype=pl.Int32),
    ).join(realized.select("player_id", "actual_vorp"), on="player_id", how="left")
    grouped = (
        board.filter(pl.col("actual_vorp").is_not_null())
        .group_by("tier_ordinal")
        .agg(pl.col("actual_vorp").mean().alias("mean_actual_vorp"), pl.len().alias("players"))
        .sort("tier_ordinal")
    )
    values = grouped.get_column("mean_actual_vorp").to_list()
    pairs = list(zip(values, values[1:], strict=False))
    monotone = [bool(later <= earlier) for earlier, later in pairs]
    return {
        **scenario.to_dict(),
        "tiers": grouped.height,
        "adjacent_pairs": len(pairs),
        "monotonic_pairs": int(sum(monotone)),
        "monotonic_pair_share": float(np.mean(monotone)) if monotone else float("nan"),
        "mean_actual_vorp_by_tier": grouped.to_dicts(),
    }


def run_tier_study(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    realized_vorp: pl.DataFrame,
    league: LeagueConfig,
    *,
    config: TierStudyConfig,
) -> TierStudyResult:
    """Select the tier penalty, then measure the promoted segmentation's stability."""
    started = time.monotonic()
    sealed = [
        season for season in predictions.get_column("season").unique().to_list() if season >= 2025
    ]
    if sealed:
        raise ValueError(
            f"out-of-fold predictions contain sealed season(s) {sorted(sealed)}; the tier "
            "study runs on development folds only",
        )

    shape: list[dict[str, Any]] = []
    boards: dict[str, tuple[pl.DataFrame, dict[float, Segmentation]]] = {}
    for scenario in config.scenarios():
        _, ranked, _ = _simulate_board(predictions, modelling_frame, league, scenario, config)
        segmentations = {
            penalty: segment_board(ranked, penalty=penalty) for penalty in config.penalties
        }
        boards[scenario.key] = (ranked, segmentations)
        for penalty, segmentation in segmentations.items():
            shape.append(
                {
                    **scenario.to_dict(),
                    "penalty": penalty,
                    "tier_count": segmentation.tier_count,
                    "singleton_rate": segmentation.singleton_rate,
                    "largest_tier_share": segmentation.largest_tier_share,
                    "mean_boundary_effect_size": segmentation.mean_boundary_effect_size,
                    "median_within_tier_effect_size": segmentation.median_within_tier_effect_size,
                    "sizes": list(segmentation.sizes),
                },
            )

    # The bootstrap is the expensive half, so it runs on a declared subset and evaluates
    # every penalty against the same replicates.
    aggregated: dict[float, list[Any]] = {penalty: [] for penalty in config.penalties}
    for scenario in [
        DevelopmentScenario(season, scoring, _DEFAULT_LEAGUE)
        for season in config.bootstrap_seasons
        for scoring in config.scoring_presets
    ]:
        players, ranked, result = _simulate_board(
            predictions,
            modelling_frame,
            league,
            scenario,
            config,
            keep_draws=True,
        )
        assert result.vorp_draws is not None and result.point_draws is not None
        promoted = {penalty: segment_board(ranked, penalty=penalty) for penalty in config.penalties}
        reports = bootstrap_stability(
            players,
            result.vorp_draws,
            result.point_draws,
            promoted=promoted,
            promoted_player_ids=ranked.get_column("player_id").to_list(),
            statistic=config.statistic,
            board_depth=config.board_depth,
            replicates=config.bootstrap_replicates,
            seed=config.seed + scenario.season,
        )
        for penalty, report in reports.items():
            aggregated[penalty].append(report)

    pooled = {penalty: _pool(reports) for penalty, reports in aggregated.items() if reports}
    penalty_decision = select_tier_penalty(
        _candidate_evidence(shape, pooled, config.penalties),
    )
    penalty = float(penalty_decision.selected) if penalty_decision.decisive else float("nan")

    monotonicity: list[dict[str, Any]] = []
    boundary_diagnostics: list[dict[str, Any]] = []
    example_board: list[dict[str, Any]] = []
    if penalty_decision.decisive:
        for scenario in config.scenarios():
            ranked, segmentations = boards[scenario.key]
            segmentation = segmentations[penalty]
            realized = realized_vorp.filter(
                (pl.col("season") == scenario.season)
                & (pl.col("scoring_preset") == scenario.scoring_preset)
                & (pl.col("league_preset_id") == scenario.league_preset_id),
            )
            monotonicity.append(_monotonicity(ranked, segmentation, realized, scenario))
            boundary_diagnostics.extend(
                {**scenario.to_dict(), **item.to_dict()} for item in segmentation.diagnostics
            )
        example = config.scenarios()[-1]
        ranked, segmentations = boards[example.key]
        example_board = _board_preview(ranked, segmentations[penalty], example)

    cross_preset = _cross_preset(predictions, modelling_frame, league, config, penalty)

    stability_report = pooled.get(penalty)
    monotone_share = (
        float(np.nanmean([row["monotonic_pair_share"] for row in monotonicity]))
        if monotonicity
        else float("nan")
    )
    cross_preset_ari = (
        float(np.nanmean([row["adjusted_rand"] for row in cross_preset]))
        if cross_preset
        else float("nan")
    )
    evidence = TierStabilityEvidence(
        bootstrap_adjusted_rand=(
            float(stability_report.adjusted_rand) if stability_report else float("nan")
        ),
        boundary_agreement=(
            float(stability_report.boundary_agreement) if stability_report else float("nan")
        ),
        singleton_rate=(
            float(stability_report.singleton_rate) if stability_report else float("nan")
        ),
        tier_count_cv=(float(stability_report.tier_count_cv) if stability_report else float("nan")),
        monotonic_pair_share=monotone_share,
        cross_preset_adjusted_rand=cross_preset_ari,
    )
    stability_decision = evaluate_tier_stability(evidence)

    return TierStudyResult(
        config=config,
        boards=shape,
        penalty_candidates=[
            item.to_dict() for item in _candidate_evidence(shape, pooled, config.penalties)
        ],
        penalty_decision=penalty_decision,
        stability_by_penalty={str(key): report.to_dict() for key, report in sorted(pooled.items())},
        stability_decision=stability_decision,
        stability_evidence=evidence.to_dict(),
        boundary_diagnostics=boundary_diagnostics,
        monotonicity=monotonicity,
        cross_preset=cross_preset,
        example_board=example_board,
        checks=_tier_checks(penalty_decision, stability_decision),
        runtime_seconds=round(time.monotonic() - started, 2),
    )


def _pool(reports: Sequence[Any]) -> Any:
    """Average several scenarios' stability reports into one."""
    from ffdraft.tiers.stability import StabilityReport

    counts = tuple(count for report in reports for count in report.tier_counts)
    frequency: dict[int, list[float]] = {}
    for report in reports:
        for position, value in report.boundary_frequency.items():
            frequency.setdefault(position, []).append(value)
    by_region: dict[str, list[float]] = {}
    for report in reports:
        for region, value in report.boundary_frequency_by_region.items():
            by_region.setdefault(region, []).append(value)
    return StabilityReport(
        replicates=int(sum(report.replicates for report in reports)),
        adjusted_rand=float(np.nanmean([report.adjusted_rand for report in reports])),
        boundary_agreement=float(np.nanmean([report.boundary_agreement for report in reports])),
        singleton_rate=float(np.nanmean([report.singleton_rate for report in reports])),
        tier_count_cv=float(np.nanmean([report.tier_count_cv for report in reports])),
        tier_counts=counts,
        boundary_frequency={
            position: float(np.mean(values)) for position, values in sorted(frequency.items())
        },
        boundary_frequency_by_region={
            region: float(np.mean(values)) for region, values in sorted(by_region.items())
        },
    )


def _cross_preset(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    league: LeagueConfig,
    config: TierStudyConfig,
    penalty: float,
) -> list[dict[str, Any]]:
    """Membership similarity between boards that differ only in preset."""
    if penalty != penalty:
        return []
    memberships: dict[str, dict[str, int]] = {}
    for scenario in config.preset_scenarios():
        if scenario.league_preset_id not in league.presets:
            continue
        _, ranked, _ = _simulate_board(predictions, modelling_frame, league, scenario, config)
        segmentation = segment_board(ranked, penalty=penalty)
        memberships[scenario.key] = dict(
            zip(ranked.get_column("player_id").to_list(), segmentation.ordinals, strict=True),
        )
    rows: list[dict[str, Any]] = []
    keys = sorted(memberships)
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            shared = [pid for pid in memberships[left] if pid in memberships[right]]
            if len(shared) < 2:
                continue
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "shared_players": len(shared),
                    "adjusted_rand": adjusted_rand_index(
                        [memberships[left][pid] for pid in shared],
                        [memberships[right][pid] for pid in shared],
                    ),
                },
            )
    return rows


def _board_preview(
    ranked: pl.DataFrame,
    segmentation: Segmentation,
    scenario: DevelopmentScenario,
) -> list[dict[str, Any]]:
    """The top of one board, so a reader can see what a tier actually looks like."""
    board = ranked.with_columns(
        pl.Series("tier_ordinal", list(segmentation.ordinals), dtype=pl.Int32),
    ).head(40)
    return [
        {
            **scenario.to_dict(),
            "fair_rank": int(row["fair_rank"]),
            "position": str(row["position"]),
            "position_rank": int(row["position_rank"]),
            "tier_ordinal": int(row["tier_ordinal"]),
            "tier_label": tier_label(int(row["tier_ordinal"])),
            "expected_vorp": float(row["expected_vorp"]),
            "p50_vorp": float(row["p50_vorp"]),
            "uncertainty": float(row["uncertainty"]),
        }
        for row in board.iter_rows(named=True)
    ]


def _tier_checks(penalty: Decision, stability: Decision) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    if penalty.decisive:
        checks.append(
            QualityCheck.ok(
                "phase4.tier_penalty",
                stage="phase4_tiers",
                message=f"{penalty.rule} selected penalty {penalty.selected}",
                observed="; ".join(penalty.reasons),
            ),
        )
    else:
        checks.append(
            QualityCheck.fail(
                "phase4.tier_penalty",
                stage="phase4_tiers",
                message="no penalty in the frozen grid was admissible",
                observed="; ".join(penalty.failures),
            ),
        )
    if stability.decisive:
        checks.append(
            QualityCheck.ok(
                "phase4.tier_stability",
                stage="phase4_tiers",
                message=f"{stability.rule} passed",
                observed="; ".join(stability.reasons),
            ),
        )
    else:
        checks.append(
            QualityCheck.fail(
                "phase4.tier_stability",
                stage="phase4_tiers",
                message=(
                    "the promoted segmentation failed the frozen stability gate; the "
                    "documented response is the dynamic-programming alternative in "
                    "docs/MODELING.md section 14.3, not a wider penalty search"
                ),
                observed="; ".join(stability.failures),
            ),
        )
    return checks


# ---------------------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------------------


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


def to_json(
    result: TierStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    stamped = generated_at or utc_now()
    return {
        "study": TIER_STUDY_VERSION,
        "study_id": (
            f"{TIER_STUDY_VERSION}:{result.config.seed}:{stamped.strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "generated_at_utc": isoformat_utc(stamped),
        "git_sha": git_sha or "unknown",
        "runtime_seconds": result.runtime_seconds,
        "configuration": result.config.to_dict(),
        "selection_criteria": TIER_SELECTION.to_dict(),
        "stability_gate": TIER_STABILITY_GATE.to_dict(),
        "segmentation_shape": result.boards,
        "penalty_candidates": result.penalty_candidates,
        "penalty_decision": result.penalty_decision.to_dict(),
        "stability_by_penalty": result.stability_by_penalty,
        "stability_evidence": result.stability_evidence,
        "stability_decision": result.stability_decision.to_dict(),
        "boundary_diagnostics": result.boundary_diagnostics,
        "tier_monotonicity": result.monotonicity,
        "cross_preset_similarity": result.cross_preset,
        "example_board": result.example_board,
        "checks": [check.to_dict() for check in result.checks],
        "status": "pass" if result.passed else "fail",
    }


def to_markdown(
    result: TierStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    stamped = generated_at or utc_now()
    lines: list[str] = [
        "# Phase 4, stage C — tier segmentation",
        "",
        (
            f"Study `{TIER_STUDY_VERSION}`, seed `{result.config.seed}`, code "
            f"`{git_sha or 'unknown'}`, generated {isoformat_utc(stamped)}. "
            f"{result.config.draws} draws, ranked by `{result.config.statistic}`, board "
            f"depth {result.config.board_depth}."
        ),
        "",
        "## Conclusion",
        "",
        f"**Penalty `{result.penalty_decision.selected}`** for "
        f"`ruptures.Pelt(model='rbf')` on standardized P25/P50/P75/spread VORP in fair-rank "
        "order.",
        "",
    ]
    for label, decision in (
        ("Penalty selection", result.penalty_decision),
        ("Stability gate", result.stability_decision),
    ):
        verdict = "passed" if decision.decisive else "failed"
        lines.append(f"**{label}** (`{decision.rule}`) — {verdict}.")
        lines.append("")
        for reason in decision.reasons:
            lines.append(f"> {reason}")
        for failure in decision.failures:
            lines.append(f"> **failed:** {failure}")
        lines.append("")

    lines.extend(
        [
            "## Penalty grid",
            "",
            "Shape diagnostics averaged over every development season and scoring preset; "
            "stability from the declared bootstrap subset.",
            "",
            _table(
                result.penalty_candidates,
                (
                    ("Penalty", "penalty"),
                    ("Mean tiers", "mean_tier_count"),
                    ("Singleton rate", "singleton_rate"),
                    ("Largest tier", "largest_tier_share"),
                    ("Boundary effect", "mean_boundary_effect_size"),
                    ("Within-tier effect", "median_within_tier_effect_size"),
                    ("Bootstrap ARI", "bootstrap_adjusted_rand"),
                    ("Boundary agreement", "boundary_agreement"),
                ),
            ),
            "",
            "## Stability of the promoted segmentation",
            "",
            _table(
                [result.stability_evidence],
                (
                    ("Bootstrap ARI", "bootstrap_adjusted_rand"),
                    ("Boundary agreement", "boundary_agreement"),
                    ("Singleton rate", "singleton_rate"),
                    ("Tier-count CV", "tier_count_cv"),
                    ("Monotonic tier pairs", "monotonic_pair_share"),
                    ("Cross-preset ARI", "cross_preset_adjusted_rand"),
                ),
            ),
            "",
            "## Tier monotonicity against realized VORP",
            "",
            _table(
                result.monotonicity,
                (
                    ("Season", "season"),
                    ("Scoring", "scoring_preset"),
                    ("Tiers", "tiers"),
                    ("Adjacent pairs", "adjacent_pairs"),
                    ("Monotonic", "monotonic_pairs"),
                    ("Share", "monotonic_pair_share"),
                ),
            ),
            "",
            "## Cross-preset membership similarity",
            "",
            _table(
                result.cross_preset,
                (
                    ("Left", "left"),
                    ("Right", "right"),
                    ("Shared", "shared_players"),
                    ("ARI", "adjusted_rand"),
                ),
            ),
            "",
            "## Example board",
            "",
            "The top 40 of one development board, so the shape of a tier is visible rather "
            "than described.",
            "",
            _table(
                result.example_board,
                (
                    ("Rank", "fair_rank"),
                    ("Pos", "position"),
                    ("Pos rank", "position_rank"),
                    ("Tier", "tier_label"),
                    ("E[VORP]", "expected_vorp"),
                    ("P50 VORP", "p50_vorp"),
                    ("Spread", "uncertainty"),
                ),
            ),
            "",
            "## Checks",
            "",
        ],
    )
    for check in result.checks:
        mark = "ok" if check.status is CheckStatus.PASS else str(check.severity)
        lines.append(f"- [{mark}] `{check.check_id}` — {check.message}")
    lines.append("")
    lines.append(
        "Tier letters are ordinal labels. `S` above `A` means the segmentation put a break "
        "between them, nothing more; no letter carries a claim about how much better one "
        "group is than the next.",
    )
    lines.append("")
    return "\n".join(lines)


def write_tier_report(
    result: TierStudyResult,
    out_dir: Path,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = generated_at or utc_now()
    payload = to_json(result, git_sha=git_sha, generated_at=stamped)
    json_path = out_dir / "experiment.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = out_dir / "experiment.md"
    markdown_path.write_text(
        to_markdown(result, git_sha=git_sha, generated_at=stamped),
        encoding="utf-8",
    )
    return [json_path, markdown_path]
