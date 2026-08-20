"""Phase 4, stage C: the Monte Carlo draw count and the production ranking statistic.

Two decisions, both taken by rules ADR-030 froze, both measured on development folds only:

**How many draws?** ``phase4_convergence_v1`` compares a ladder of draw counts on
representative historical scenarios. A count qualifies only if every declared tolerance
holds twice - against the largest count in the ladder at the same seed, and between two
seeds at the same count. The first measures bias against the best available reference; only
the second measures Monte Carlo error directly, which is why one comparison would not be
enough. The smallest qualifying count wins, because simulation time is a cost and buying
precision nobody can see is waste.

**Expected or median simulated VORP?** ``phase4_ranking_v1`` compares the two orderings
against the *realized* VORP labels Phase 2 built, over the full eligible universe of each
development season. ADR-029 recorded the reason this is measured rather than assumed: Q1's
median point prediction ordered players better than the ridge baseline by rank correlation
and yet retrieved fewer of the actual top-K, and the top of the board is where a draft sheet
earns its keep.

Both run over the out-of-fold predictions the stage-B study wrote, which are the promoted
architecture's predictions for validation seasons it never trained on. The sealed 2025
season is not among them.
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
from numpy.typing import NDArray

from ffdraft.config import LeagueConfig, LeaguePreset
from ffdraft.contracts import CheckStatus, QualityCheck
from ffdraft.modeling.folds import DEFAULT_SEED, DEVELOPMENT_VALIDATION_SEASONS
from ffdraft.modeling.metrics import (
    QUANTILE_LEVELS,
    TOP_K_BY_POSITION,
    kendall_tau_b,
    spearman,
    top_k_recall,
)
from ffdraft.modeling.rules import (
    CONVERGENCE_TOLERANCE,
    TIER_BOARD_DEPTH,
    TIER_PENALTY_GRID,
    ConvergenceEvidence,
    Decision,
    RankingEvidence,
    evaluate_convergence,
    evaluate_ranking_choice,
)
from ffdraft.simulation.sampler import DomainBounds
from ffdraft.simulation.vorp import (
    SimulationConfig,
    SimulationResult,
    fair_ranking,
    sample_points,
    simulate_vorp,
)
from ffdraft.tiers.segmentation import segment_board
from ffdraft.tiers.stability import adjusted_rand_index
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "CONVERGENCE_SCENARIOS",
    "OOF_QUANTILE_COLUMNS",
    "SIMULATION_STUDY_VERSION",
    "DevelopmentScenario",
    "SimulationStudyConfig",
    "SimulationStudyResult",
    "load_oof_predictions",
    "run_simulation_study",
    "training_bounds",
    "write_simulation_report",
]

Floats = NDArray[np.float64]

SIMULATION_STUDY_VERSION = "phase4_simulation_v1"

#: The stage-B prediction frame's quantile columns, low to high.
OOF_QUANTILE_COLUMNS: tuple[str, ...] = ("q10", "q25", "q50", "q75", "q90")

#: A secondary retrieval depth: roughly the first two rounds of a 12-team draft, where a
#: mistake is most expensive.
EARLY_ROUND_DEPTH = 24


@dataclass(frozen=True, slots=True)
class DevelopmentScenario:
    """One (validation season, scoring preset, league preset) board."""

    season: int
    scoring_preset: str
    league_preset_id: str

    @property
    def key(self) -> str:
        return f"{self.season}/{self.scoring_preset}/{self.league_preset_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "scoring_preset": self.scoring_preset,
            "league_preset_id": self.league_preset_id,
        }


#: Convergence is measured on four scenarios rather than all forty-five: the draw count is
#: one global choice, the tolerances must hold in every scenario, and these four span both
#: ends of the season range, all three scoring presets and all three league sizes. Declared
#: here rather than chosen after seeing which ones converge fastest.
CONVERGENCE_SCENARIOS: tuple[DevelopmentScenario, ...] = (
    DevelopmentScenario(2022, "PPR", "redraft-12"),
    DevelopmentScenario(2024, "PPR", "redraft-12"),
    DevelopmentScenario(2024, "STD", "redraft-10"),
    DevelopmentScenario(2023, "HALF", "redraft-14"),
)


@dataclass(frozen=True)
class SimulationStudyConfig:
    """Everything that makes the stage-C simulation study reproducible."""

    seed: int = DEFAULT_SEED
    second_seed: int = DEFAULT_SEED + 1
    validation_seasons: tuple[int, ...] = DEVELOPMENT_VALIDATION_SEASONS
    scoring_presets: tuple[str, ...] = ("STD", "HALF", "PPR")
    league_presets: tuple[str, ...] = ("redraft-10", "redraft-12", "redraft-14")
    convergence_scenarios: tuple[DevelopmentScenario, ...] = CONVERGENCE_SCENARIOS
    board_depth: int = TIER_BOARD_DEPTH
    levels: tuple[float, ...] = QUANTILE_LEVELS
    model_version: str = "phase4_development"

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_version": SIMULATION_STUDY_VERSION,
            "seed": self.seed,
            "second_seed": self.second_seed,
            "validation_seasons": list(self.validation_seasons),
            "scoring_presets": list(self.scoring_presets),
            "league_presets": list(self.league_presets),
            "convergence_scenarios": [item.to_dict() for item in self.convergence_scenarios],
            "draw_ladder": list(CONVERGENCE_TOLERANCE.draw_ladder),
            "board_depth": self.board_depth,
            "levels": list(self.levels),
            "model_version": self.model_version,
        }

    def ranking_scenarios(self, league: LeagueConfig) -> list[DevelopmentScenario]:
        return [
            DevelopmentScenario(season, scoring, preset)
            for season in self.validation_seasons
            for scoring in self.scoring_presets
            for preset in self.league_presets
            if preset in league.presets
        ]


@dataclass
class SimulationStudyResult:
    """Everything stage C's simulation half produced."""

    config: SimulationStudyConfig
    convergence_measurements: list[dict[str, Any]]
    convergence_decision: Decision
    ranking_cells: list[dict[str, Any]]
    ranking_evidence: dict[str, dict[str, Any]]
    ranking_decision: Decision
    replacement_summary: list[dict[str, Any]]
    determinism: dict[str, Any]
    checks: list[QualityCheck] = field(default_factory=list)
    runtime_seconds: float = 0.0

    @property
    def draws(self) -> int:
        return int(self.convergence_decision.selected)

    @property
    def statistic(self) -> str:
        return str(self.ranking_decision.selected)

    @property
    def passed(self) -> bool:
        return all(not check.blocking for check in self.checks)


# ---------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------


def load_oof_predictions(path: Path) -> pl.DataFrame:
    """Read the promoted architecture's out-of-fold predictions written by stage B."""
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found; run `ffdraft evaluate-distribution` first so stage C has "
            "out-of-fold predictions to simulate",
        )
    frame = pl.read_parquet(path)
    missing = [name for name in OOF_QUANTILE_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"out-of-fold predictions are missing quantile column(s) {missing}")
    return frame


def training_bounds(
    modelling_frame: pl.DataFrame,
    *,
    season: int,
    scoring_preset: str,
    target_column: str = "target_points",
) -> dict[str, DomainBounds]:
    """Domain bounds per position from seasons strictly before ``season``.

    Fold-local by construction: the sampler's guard rails are estimated from training rows
    only, so nothing about the season being simulated leaks into the range its own draws are
    allowed to take.
    """
    training = modelling_frame.filter(
        (pl.col("season") < season) & (pl.col("scoring_preset") == scoring_preset),
    )
    bounds: dict[str, DomainBounds] = {}
    for (position,), block in training.group_by(["position"], maintain_order=True):
        bounds[str(position)] = DomainBounds.from_training(
            block.get_column(target_column).cast(pl.Float64).to_numpy(),
        )
    return bounds


def _projections(predictions: pl.DataFrame, scenario: DevelopmentScenario) -> pl.DataFrame:
    return predictions.filter(
        (pl.col("season") == scenario.season)
        & (pl.col("scoring_preset") == scenario.scoring_preset),
    ).sort("player_id")


def _simulate(
    projections: pl.DataFrame,
    *,
    preset: LeaguePreset,
    scenario: DevelopmentScenario,
    draws: int,
    seed: int,
    config: SimulationStudyConfig,
    bounds: Mapping[str, DomainBounds],
    points: Floats | None = None,
) -> tuple[SimulationResult, Floats]:
    simulation_config = SimulationConfig(
        draws=draws,
        seed=seed,
        model_version=config.model_version,
        scoring_preset=scenario.scoring_preset,
        build_id=f"development:{scenario.season}",
        levels=config.levels,
    )
    sampled = (
        sample_points(
            projections,
            config=simulation_config,
            bounds=bounds,
            quantile_columns=OOF_QUANTILE_COLUMNS,
        )
        if points is None
        else points
    )
    result = simulate_vorp(
        projections,
        preset=preset,
        config=simulation_config,
        bounds=bounds,
        points=sampled,
    )
    return result, sampled


# ---------------------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------------------


def _rank_vector(players: pl.DataFrame, statistic: str, depth: int) -> pl.DataFrame:
    return fair_ranking(players, statistic=statistic).head(depth)


def _compare(
    left_result: SimulationResult,
    right_result: SimulationResult,
    *,
    scenario: DevelopmentScenario,
    comparison: str,
    draws: int,
    board_depth: int,
) -> ConvergenceEvidence:
    """Every convergence tolerance, measured between two runs of the same scenario."""
    left, right = left_result.players, right_result.players
    joined = left.join(right, on="player_id", how="inner", suffix="_other")

    def difference(column: str) -> Floats:
        left_values = np.asarray(
            joined.get_column(column).cast(pl.Float64).to_numpy(),
            dtype=np.float64,
        )
        right_values = np.asarray(
            joined.get_column(f"{column}_other").cast(pl.Float64).to_numpy(),
            dtype=np.float64,
        )
        return np.abs(left_values - right_values)

    expected = difference("expected_vorp")
    median = difference("p50_vorp")
    outer = np.concatenate([difference("p10_vorp"), difference("p90_vorp")])

    # Fair ranks and tiers are compared under both candidate ranking statistics and at every
    # penalty in the frozen grid: the draw count is chosen before either of those decisions,
    # so it has to be sufficient for whichever way they go.
    rank_spearman: list[float] = []
    overlap: list[float] = []
    rank_change: list[float] = []
    tier_rand: list[float] = []
    tier_difference: list[int] = []
    for statistic in ("median_vorp", "expected_vorp"):
        left_board = _rank_vector(left, statistic, board_depth)
        right_board = _rank_vector(right, statistic, board_depth)
        merged = left_board.select("player_id", "fair_rank").join(
            right_board.select("player_id", "fair_rank"),
            on="player_id",
            how="inner",
            suffix="_other",
        )
        if merged.height > 1:
            a = merged.get_column("fair_rank").cast(pl.Float64).to_numpy()
            b = merged.get_column("fair_rank_other").cast(pl.Float64).to_numpy()
            rank_spearman.append(spearman(a, b))
            top_150 = merged.filter(pl.col("fair_rank") <= 150)
            if top_150.height:
                rank_change.append(
                    float(
                        np.mean(
                            np.abs(
                                top_150.get_column("fair_rank").cast(pl.Float64).to_numpy()
                                - top_150.get_column("fair_rank_other").cast(pl.Float64).to_numpy(),
                            ),
                        ),
                    ),
                )
        left_top = set(left_board.head(50).get_column("player_id").to_list())
        right_top = set(right_board.head(50).get_column("player_id").to_list())
        overlap.append(len(left_top & right_top) / 50.0 if left_top else float("nan"))

        for penalty in TIER_PENALTY_GRID:
            left_segmentation = segment_board(left_board, penalty=penalty)
            right_segmentation = segment_board(right_board, penalty=penalty)
            left_map = dict(
                zip(
                    left_board.get_column("player_id").to_list(),
                    left_segmentation.ordinals,
                    strict=True,
                ),
            )
            right_map = dict(
                zip(
                    right_board.get_column("player_id").to_list(),
                    right_segmentation.ordinals,
                    strict=True,
                ),
            )
            shared = [pid for pid in left_map if pid in right_map]
            if len(shared) > 1:
                tier_rand.append(
                    adjusted_rand_index(
                        [left_map[pid] for pid in shared],
                        [right_map[pid] for pid in shared],
                    ),
                )
            tier_difference.append(
                left_segmentation.tier_count - right_segmentation.tier_count,
            )

    return ConvergenceEvidence(
        scenario=scenario.key,
        comparison=comparison,
        draws=draws,
        mean_abs_expected_vorp=float(np.mean(expected)),
        p99_abs_expected_vorp=float(np.quantile(expected, 0.99)),
        mean_abs_p50_vorp=float(np.mean(median)),
        p99_abs_p50_vorp=float(np.quantile(median, 0.99)),
        mean_abs_outer_vorp=float(np.mean(outer)),
        p99_abs_outer_vorp=float(np.quantile(outer, 0.99)),
        max_abs_replacement=_replacement_gap(left_result, right_result),
        fair_rank_spearman=float(np.min(rank_spearman)) if rank_spearman else float("nan"),
        top_50_overlap=float(np.min(overlap)) if overlap else float("nan"),
        mean_abs_rank_change_top_150=(float(np.max(rank_change)) if rank_change else float("nan")),
        tier_adjusted_rand=float(np.min(tier_rand)) if tier_rand else float("nan"),
        tier_count_difference=(int(max(tier_difference, key=abs)) if tier_difference else 0),
    )


def _replacement_gap(left: SimulationResult, right: SimulationResult) -> float:
    left_map = {row["position"]: row["mean"] for row in left.replacement}
    right_map = {row["position"]: row["mean"] for row in right.replacement}
    gaps = [
        abs(float(left_map[position]) - float(right_map[position]))
        for position in left_map
        if left_map.get(position) is not None and right_map.get(position) is not None
    ]
    return float(max(gaps)) if gaps else float("nan")


def _run_convergence(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    league: LeagueConfig,
    config: SimulationStudyConfig,
) -> tuple[list[ConvergenceEvidence], list[dict[str, Any]]]:
    """Measure every ladder step against the reference count and against a second seed."""
    evidence: list[ConvergenceEvidence] = []
    determinism: list[dict[str, Any]] = []
    reference_draws = CONVERGENCE_TOLERANCE.reference_draws

    for scenario in config.convergence_scenarios:
        projections = _projections(predictions, scenario)
        if projections.height == 0:
            continue
        preset = league.preset(scenario.league_preset_id)
        bounds = training_bounds(
            modelling_frame,
            season=scenario.season,
            scoring_preset=scenario.scoring_preset,
        )
        reference, _ = _simulate(
            projections,
            preset=preset,
            scenario=scenario,
            draws=reference_draws,
            seed=config.seed,
            config=config,
            bounds=bounds,
        )
        repeat, _ = _simulate(
            projections,
            preset=preset,
            scenario=scenario,
            draws=reference_draws,
            seed=config.seed,
            config=config,
            bounds=bounds,
        )
        determinism.append(
            {
                "scenario": scenario.key,
                "draws": reference_draws,
                "identical_expected_vorp": bool(
                    np.array_equal(
                        reference.players.get_column("expected_vorp").to_numpy(),
                        repeat.players.get_column("expected_vorp").to_numpy(),
                    ),
                ),
            },
        )
        for draws in CONVERGENCE_TOLERANCE.draw_ladder:
            primary, _ = (
                (reference, None)
                if draws == reference_draws
                else _simulate(
                    projections,
                    preset=preset,
                    scenario=scenario,
                    draws=draws,
                    seed=config.seed,
                    config=config,
                    bounds=bounds,
                )
            )
            secondary, _ = _simulate(
                projections,
                preset=preset,
                scenario=scenario,
                draws=draws,
                seed=config.second_seed,
                config=config,
                bounds=bounds,
            )
            evidence.append(
                _compare(
                    primary,
                    reference,
                    scenario=scenario,
                    comparison="vs_reference",
                    draws=draws,
                    board_depth=config.board_depth,
                ),
            )
            evidence.append(
                _compare(
                    primary,
                    secondary,
                    scenario=scenario,
                    comparison="vs_second_seed",
                    draws=draws,
                    board_depth=config.board_depth,
                ),
            )
    return evidence, determinism


# ---------------------------------------------------------------------------------------
# Expected versus median simulated VORP
# ---------------------------------------------------------------------------------------


def _ranking_cell(
    ranked: pl.DataFrame,
    realized: pl.DataFrame,
    *,
    scenario: DevelopmentScenario,
    statistic: str,
    starter_depth: int,
) -> dict[str, Any]:
    """One scenario's ranking metrics against realized VORP."""
    joined = ranked.join(
        realized.select("player_id", "actual_vorp"),
        on="player_id",
        how="inner",
    ).filter(pl.col("actual_vorp").is_not_null())
    if joined.height < 2:
        return {}
    actual = joined.get_column("actual_vorp").cast(pl.Float64).to_numpy()
    # Fair rank ascends as value descends, so the predicted "score" is its negation.
    predicted = -joined.get_column("fair_rank").cast(pl.Float64).to_numpy()
    record: dict[str, Any] = {
        **scenario.to_dict(),
        "statistic": statistic,
        "n": int(joined.height),
        "spearman": spearman(actual, predicted),
        "kendall_tau_b": kendall_tau_b(actual, predicted),
        "top_k": starter_depth,
        "top_k_recall": top_k_recall(actual, predicted, starter_depth),
        "early_round_recall": top_k_recall(actual, predicted, EARLY_ROUND_DEPTH),
    }
    for (position,), block in joined.group_by(["position"], maintain_order=True):
        depth = TOP_K_BY_POSITION.get(str(position), 0)
        if depth:
            record[f"top_k_recall_{position}"] = top_k_recall(
                block.get_column("actual_vorp").cast(pl.Float64).to_numpy(),
                -block.get_column("fair_rank").cast(pl.Float64).to_numpy(),
                depth,
            )
    return record


def _macro(rows: Sequence[Mapping[str, Any]], key: str, **filters: Any) -> float:
    values = [
        float(row[key])
        for row in rows
        if all(row.get(name) == value for name, value in filters.items())
        and row.get(key) is not None
        and float(row[key]) == float(row[key])
    ]
    return float(np.mean(values)) if values else float("nan")


def _ranking_evidence(
    cells: Sequence[Mapping[str, Any]],
    statistic: str,
    *,
    seed_stability: float,
) -> RankingEvidence:
    positions = sorted(
        {
            key.removeprefix("top_k_recall_")
            for row in cells
            for key in row
            if key.startswith("top_k_recall_")
        },
    )
    return RankingEvidence(
        statistic=statistic,
        macro_spearman=_macro(cells, "spearman", statistic=statistic),
        macro_kendall=_macro(cells, "kendall_tau_b", statistic=statistic),
        macro_top_k_recall=_macro(cells, "top_k_recall", statistic=statistic),
        macro_top_k_precision=_macro(cells, "early_round_recall", statistic=statistic),
        top_k_recall_by_position={
            position: _macro(cells, f"top_k_recall_{position}", statistic=statistic)
            for position in positions
        },
        seed_rank_stability=seed_stability,
    )


def _run_ranking(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    realized_vorp: pl.DataFrame,
    league: LeagueConfig,
    config: SimulationStudyConfig,
    *,
    draws: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    """Simulate every development scenario once and score both ranking statistics on it."""
    cells: list[dict[str, Any]] = []
    replacement: list[dict[str, Any]] = []
    stability: dict[str, list[float]] = {"median_vorp": [], "expected_vorp": []}

    scenarios = config.ranking_scenarios(league)
    cache: dict[tuple[int, str], tuple[pl.DataFrame, Floats, dict[str, DomainBounds]]] = {}
    for scenario in scenarios:
        key = (scenario.season, scenario.scoring_preset)
        if key not in cache:
            projections = _projections(predictions, scenario)
            if projections.height == 0:
                continue
            bounds = training_bounds(
                modelling_frame,
                season=scenario.season,
                scoring_preset=scenario.scoring_preset,
            )
            simulation_config = SimulationConfig(
                draws=draws,
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
            cache[key] = (projections, sampled, bounds)
        projections, sampled, bounds = cache[key]
        preset = league.preset(scenario.league_preset_id)
        result, _ = _simulate(
            projections,
            preset=preset,
            scenario=scenario,
            draws=draws,
            seed=config.seed,
            config=config,
            bounds=bounds,
            points=sampled,
        )
        alternate, _ = _simulate(
            projections,
            preset=preset,
            scenario=scenario,
            draws=draws,
            seed=config.second_seed,
            config=config,
            bounds=bounds,
        )
        realized = realized_vorp.filter(
            (pl.col("season") == scenario.season)
            & (pl.col("scoring_preset") == scenario.scoring_preset)
            & (pl.col("league_preset_id") == scenario.league_preset_id),
        )
        starter_depth = preset.teams * preset.starting_slots
        for statistic in ("median_vorp", "expected_vorp"):
            ranked = fair_ranking(result.players, statistic=statistic)
            record = _ranking_cell(
                ranked,
                realized,
                scenario=scenario,
                statistic=statistic,
                starter_depth=starter_depth,
            )
            if record:
                cells.append(record)
            other = fair_ranking(alternate.players, statistic=statistic)
            merged = ranked.select("player_id", "fair_rank").join(
                other.select("player_id", "fair_rank"),
                on="player_id",
                how="inner",
                suffix="_other",
            )
            if merged.height > 1:
                stability[statistic].append(
                    spearman(
                        merged.get_column("fair_rank").cast(pl.Float64).to_numpy(),
                        merged.get_column("fair_rank_other").cast(pl.Float64).to_numpy(),
                    ),
                )
        replacement.append(
            {
                **scenario.to_dict(),
                "starter_depth": starter_depth,
                "replacement": result.replacement,
                "unfilled_slots": dict(result.unfilled_slots),
            },
        )
    return (
        cells,
        replacement,
        {
            statistic: float(np.mean(values)) if values else float("nan")
            for statistic, values in stability.items()
        },
    )


# ---------------------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------------------


def run_simulation_study(
    predictions: pl.DataFrame,
    modelling_frame: pl.DataFrame,
    realized_vorp: pl.DataFrame,
    league: LeagueConfig,
    *,
    config: SimulationStudyConfig | None = None,
) -> SimulationStudyResult:
    """Choose the draw count, then the ranking statistic, in that order."""
    started = time.monotonic()
    settings = config or SimulationStudyConfig()
    sealed = [
        season for season in predictions.get_column("season").unique().to_list() if season >= 2025
    ]
    if sealed:
        raise ValueError(
            f"out-of-fold predictions contain sealed season(s) {sorted(sealed)}; stage C runs "
            "on development folds only",
        )

    evidence, determinism = _run_convergence(predictions, modelling_frame, league, settings)
    convergence_decision = evaluate_convergence(evidence)
    draws = int(convergence_decision.selected)

    cells, replacement, seed_stability = _run_ranking(
        predictions,
        modelling_frame,
        realized_vorp,
        league,
        settings,
        draws=draws,
    )
    median = _ranking_evidence(cells, "median_vorp", seed_stability=seed_stability["median_vorp"])
    expected = _ranking_evidence(
        cells,
        "expected_vorp",
        seed_stability=seed_stability["expected_vorp"],
    )
    ranking_decision = evaluate_ranking_choice(median, expected)

    checks = _simulation_checks(convergence_decision, ranking_decision, determinism)
    return SimulationStudyResult(
        config=settings,
        convergence_measurements=[item.to_dict() for item in evidence],
        convergence_decision=convergence_decision,
        ranking_cells=cells,
        ranking_evidence={"median_vorp": median.to_dict(), "expected_vorp": expected.to_dict()},
        ranking_decision=ranking_decision,
        replacement_summary=replacement,
        determinism={"repeat_runs": determinism},
        checks=checks,
        runtime_seconds=round(time.monotonic() - started, 2),
    )


def _simulation_checks(
    convergence: Decision,
    ranking: Decision,
    determinism: Sequence[Mapping[str, Any]],
) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    if convergence.decisive:
        checks.append(
            QualityCheck.ok(
                "phase4.monte_carlo_convergence",
                stage="phase4_simulation",
                message=f"{convergence.rule} selected {convergence.selected} draws",
                observed="; ".join(convergence.reasons),
            ),
        )
    else:
        checks.append(
            QualityCheck.fail(
                "phase4.monte_carlo_convergence",
                stage="phase4_simulation",
                message="no draw count in the declared ladder satisfied every tolerance",
                observed="; ".join(convergence.failures) or "; ".join(convergence.reasons),
            ),
        )
    checks.append(
        QualityCheck.ok(
            "phase4.ranking_statistic",
            stage="phase4_simulation",
            message=f"{ranking.rule} selected {ranking.selected}",
            observed="; ".join(ranking.reasons),
        ),
    )
    repeated = [bool(item["identical_expected_vorp"]) for item in determinism]
    if repeated and all(repeated):
        checks.append(
            QualityCheck.ok(
                "phase4.simulation_deterministic",
                stage="phase4_simulation",
                message="repeating a scenario with the same inputs reproduced it exactly",
                observed=f"{len(repeated)} scenario(s), bit-identical expected VORP",
            ),
        )
    else:
        checks.append(
            QualityCheck.fail(
                "phase4.simulation_deterministic",
                stage="phase4_simulation",
                message="a repeated simulation did not reproduce its own output",
                observed=f"{sum(repeated)}/{len(repeated)} scenario(s) reproduced",
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
    result: SimulationStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    stamped = generated_at or utc_now()
    return {
        "study": SIMULATION_STUDY_VERSION,
        "study_id": (
            f"{SIMULATION_STUDY_VERSION}:{result.config.seed}:{stamped.strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "generated_at_utc": isoformat_utc(stamped),
        "git_sha": git_sha or "unknown",
        "runtime_seconds": result.runtime_seconds,
        "configuration": result.config.to_dict(),
        "convergence_tolerance": CONVERGENCE_TOLERANCE.to_dict(),
        "convergence_measurements": result.convergence_measurements,
        "convergence_decision": result.convergence_decision.to_dict(),
        "selected_draws": result.draws,
        "ranking_cells": result.ranking_cells,
        "ranking_evidence": result.ranking_evidence,
        "ranking_decision": result.ranking_decision.to_dict(),
        "selected_ranking_statistic": result.statistic,
        "replacement_summary": result.replacement_summary,
        "determinism": result.determinism,
        "checks": [check.to_dict() for check in result.checks],
        "status": "pass" if result.passed else "fail",
    }


def to_markdown(
    result: SimulationStudyResult,
    *,
    git_sha: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    stamped = generated_at or utc_now()
    median = result.ranking_evidence["median_vorp"]
    expected = result.ranking_evidence["expected_vorp"]
    lines: list[str] = [
        "# Phase 4, stage C — Monte Carlo draw count and the fair-ranking statistic",
        "",
        (
            f"Study `{SIMULATION_STUDY_VERSION}`, seed `{result.config.seed}`, code "
            f"`{git_sha or 'unknown'}`, generated {isoformat_utc(stamped)}."
        ),
        "",
        "## Conclusion",
        "",
        f"**{result.draws} draws** and **`{result.statistic}`** as the fair-ranking statistic.",
        "",
    ]
    for label, decision in (
        ("Draw count", result.convergence_decision),
        ("Ranking statistic", result.ranking_decision),
    ):
        verdict = "decisive" if decision.decisive else "not decisive; the default stands"
        lines.append(f"**{label}** (`{decision.rule}`) selected `{decision.selected}` — {verdict}.")
        lines.append("")
        for reason in decision.reasons:
            lines.append(f"> {reason}")
        for failure in decision.failures:
            lines.append(f"> **failed:** {failure}")
        lines.append("")

    lines.extend(
        [
            "## Convergence",
            "",
            (
                "Every ladder step is compared twice: against "
                f"{CONVERGENCE_TOLERANCE.reference_draws} draws at the same seed, and against "
                "a second seed at the same count. Fair-rank and tier comparisons are taken as "
                "the worst case over both candidate ranking statistics and all six penalties "
                "in the frozen grid, because the draw count is chosen before either of those "
                "decisions is made."
            ),
            "",
            _table(
                sorted(
                    result.convergence_measurements,
                    key=lambda row: (
                        int(row["draws"]),
                        str(row["scenario"]),
                        str(row["comparison"]),
                    ),
                ),
                (
                    ("Draws", "draws"),
                    ("Scenario", "scenario"),
                    ("Comparison", "comparison"),
                    ("mean |dE[VORP]|", "mean_abs_expected_vorp"),
                    ("p99 |dE[VORP]|", "p99_abs_expected_vorp"),
                    ("mean |dP50|", "mean_abs_p50_vorp"),
                    ("mean |douter|", "mean_abs_outer_vorp"),
                    ("max |drepl|", "max_abs_replacement"),
                    ("rank rho", "fair_rank_spearman"),
                    ("top-50", "top_50_overlap"),
                    ("tier ARI", "tier_adjusted_rand"),
                ),
            ),
            "",
            "## Expected versus median simulated VORP",
            "",
            (
                "Scored against the realized VORP labels Phase 2 built, over the full eligible "
                "universe of each development season, for every scoring x league preset."
            ),
            "",
            _table(
                [
                    {"statistic": "median_vorp", **median},
                    {"statistic": "expected_vorp", **expected},
                ],
                (
                    ("Statistic", "statistic"),
                    ("Spearman", "macro_spearman"),
                    ("Kendall", "macro_kendall"),
                    ("Top-K recall", "macro_top_k_recall"),
                    ("Early-round recall", "macro_top_k_precision"),
                    ("Seed rank stability", "seed_rank_stability"),
                ),
            ),
            "",
            "Top-K retrieval by position:",
            "",
            _table(
                [
                    {
                        "position": position,
                        "median_vorp": median["top_k_recall_by_position"].get(position),
                        "expected_vorp": expected["top_k_recall_by_position"].get(position),
                    }
                    for position in sorted(median["top_k_recall_by_position"])
                ],
                (
                    ("Position", "position"),
                    ("median VORP", "median_vorp"),
                    ("expected VORP", "expected_vorp"),
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
    return "\n".join(lines)


def write_simulation_report(
    result: SimulationStudyResult,
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
