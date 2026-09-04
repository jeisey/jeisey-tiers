"""The Phase-11 rest-of-season value study.

Three questions, all of them measured rather than assumed:

1. **Which replacement interpretation?** 11.5 requires the choice between preseason draft
   opportunity cost and an in-season roster interpretation to be decided and documented. The
   study runs both rules over the same simulated seasons and reports how far apart the two
   boards actually are.
2. **How many Monte Carlo draws?** The frozen ``phase4_convergence_v1`` tolerance is reused
   unchanged - it is stated on quantities a reader of the board sees, and those quantities
   mean the same thing at the rest-of-season grain - and the same two comparisons decide:
   against the largest count in the ladder at one seed, and between two seeds at the
   candidate count.
3. **Are the tiers real?** The frozen ``phase4_tier_v1`` penalty selection and
   ``phase4_tier_stability_v1`` gate are applied to rest-of-season boards. Both are pure
   functions of measured evidence, so reusing them means the rest-of-season board is held to
   the same bar as the draft board rather than to a bar invented for it.

The study runs on the **last development fold** (train 2017-2023, evaluate 2024). It never
touches the sealed season: a value study is a design decision, and design decisions are made
before the holdout is opened.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.features.dictionary import ALL_CORE_POSITIONS
from ffdraft.modeling.metrics import QUANTILE_LEVELS, spearman
from ffdraft.modeling.rules import (
    CONVERGENCE_TOLERANCE,
    TIER_SELECTION,
    TIER_STABILITY_GATE,
    ConvergenceEvidence,
    Decision,
    TierCandidateEvidence,
    TierStabilityEvidence,
    evaluate_convergence,
    evaluate_tier_stability,
    select_tier_penalty,
)
from ffdraft.ros.candidates import RC1_VERSION, RosHurdleCandidate
from ffdraft.ros.dataset import RosDataset
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.estimators import ROS_TARGET_COLUMN, RosFitContext
from ffdraft.ros.folds import ROS_SEED, RosFold, ros_development_folds
from ffdraft.ros.value import (
    ROS_VALUE_VERSION,
    RosReplacementRule,
    allocate_with_bench,
    decide_replacement,
)
from ffdraft.simulation.allocation import PlayerPoints, allocate_starters
from ffdraft.simulation.sampler import DomainBounds
from ffdraft.simulation.vorp import (
    AllocationRule,
    SimulationConfig,
    SimulationResult,
    fair_ranking,
    quantile_column_names,
    sample_points,
    simulate_vorp,
)
from ffdraft.tiers.algorithms import ALTERNATIVE_ALGORITHM, PRIMARY_ALGORITHM, segment_with
from ffdraft.tiers.segmentation import Segmentation
from ffdraft.tiers.stability import DEFAULT_BOOTSTRAP_REPLICATES, bootstrap_stability
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ROS_VALUE_STUDY_VERSION",
    "STUDY_SNAPSHOT_WEEKS",
    "RosValueStudyConfig",
    "RosValueStudyResult",
    "run_ros_value_study",
]

#: Bump when the study's construction changes in a way that moves a reported number.
ROS_VALUE_STUDY_VERSION = "phase11_ros_value_v1"

#: The snapshot weeks the study reports on, declared before it ran: one week into the season,
#: one before the first byes bite, one at midseason and one at the start of the fantasy
#: playoff run-in.
STUDY_SNAPSHOT_WEEKS: tuple[int, ...] = (1, 4, 8, 12)

#: The weeks the convergence ladder is measured on. Two is enough to see both a long horizon
#: and a short one, and each ladder rung is a full simulation.
CONVERGENCE_WEEKS: tuple[int, ...] = (4, 12)

#: The board depth tiers are cut at. Release 1's frozen depth, reused so the frozen tier
#: thresholds - which were calibrated against a 300-row board - still mean what they meant.
ROS_BOARD_DEPTH = TIER_SELECTION.board_depth

_POINT_COLUMNS = tuple(quantile_column_names("points", QUANTILE_LEVELS))


@dataclass(frozen=True)
class RosValueStudyConfig:
    """Everything one value study is a function of."""

    fold: RosFold = field(default_factory=lambda: ros_development_folds()[-1])
    weeks: tuple[int, ...] = STUDY_SNAPSHOT_WEEKS
    convergence_weeks: tuple[int, ...] = CONVERGENCE_WEEKS
    scoring_presets: tuple[str, ...] = ("STD", "HALF", "PPR")
    league_preset_id: str = "redraft-12"
    positions: tuple[str, ...] = ALL_CORE_POSITIONS
    seed: int = ROS_SEED
    alternate_seed: int = ROS_SEED + 1
    draws: int = CONVERGENCE_TOLERANCE.reference_draws
    board_depth: int = ROS_BOARD_DEPTH
    stability_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES
    levels: tuple[float, ...] = QUANTILE_LEVELS

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_version": ROS_VALUE_STUDY_VERSION,
            "value_version": ROS_VALUE_VERSION,
            "model_version": RC1_VERSION,
            "fold": self.fold.to_dict(),
            "weeks": list(self.weeks),
            "convergence_weeks": list(self.convergence_weeks),
            "scoring_presets": list(self.scoring_presets),
            "league_preset_id": self.league_preset_id,
            "seed": self.seed,
            "alternate_seed": self.alternate_seed,
            "reference_draws": self.draws,
            "board_depth": self.board_depth,
            "stability_replicates": self.stability_replicates,
        }


@dataclass
class RosValueStudyResult:
    """Everything one value study produced."""

    config: RosValueStudyConfig
    replacement_sensitivity: tuple[dict[str, Any], ...]
    replacement_decision: Decision
    convergence_evidence: tuple[ConvergenceEvidence, ...]
    convergence_decision: Decision
    tier_shape: tuple[dict[str, Any], ...]
    tier_decision: Decision
    tier_stability: dict[str, Any]
    stability_decision: Decision
    boards: dict[str, list[dict[str, Any]]]
    checks: tuple[QualityCheck, ...] = ()
    generated_at: Any = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": isoformat_utc(self.generated_at),
            "configuration": self.config.to_dict(),
            "replacement": {
                "rules": {str(rule): rule.description for rule in RosReplacementRule},
                "sensitivity": list(self.replacement_sensitivity),
                "decision": self.replacement_decision.to_dict(),
            },
            "convergence": {
                "criteria": CONVERGENCE_TOLERANCE.to_dict(),
                "evidence": [item.to_dict() for item in self.convergence_evidence],
                "decision": self.convergence_decision.to_dict(),
            },
            "tiers": {
                "criteria": TIER_SELECTION.to_dict(),
                "shape": list(self.tier_shape),
                "decision": self.tier_decision.to_dict(),
                "stability_criteria": TIER_STABILITY_GATE.to_dict(),
                "stability": self.tier_stability,
                "stability_decision": self.stability_decision.to_dict(),
            },
            "boards": self.boards,
            "checks": [check.to_dict() for check in self.checks],
        }


def _allocate(rule: RosReplacementRule) -> AllocationRule:
    return allocate_starters if rule is RosReplacementRule.FRESH_ALLOCATION else allocate_with_bench


def _projections(
    predictions: pl.DataFrame,
    *,
    week: int,
    scoring_preset: str,
) -> pl.DataFrame:
    """One snapshot's board, in the shape the sampler expects."""
    return (
        predictions.filter(
            (pl.col("through_week") == week) & (pl.col("scoring_preset") == scoring_preset),
        )
        .sort("player_id")
        .select("player_id", "position", *_POINT_COLUMNS)
    )


def _training_bounds(
    train: pl.DataFrame,
    *,
    scoring_preset: str,
    positions: Sequence[str],
) -> dict[str, DomainBounds]:
    """Per-position domain bounds from the *training* remaining-point range only."""
    scoped = train.filter(pl.col("scoring_preset") == scoring_preset)
    bounds: dict[str, DomainBounds] = {}
    for position in positions:
        values = (
            scoped.filter(pl.col("position") == position)
            .get_column(ROS_TARGET_COLUMN)
            .to_numpy()
            .astype(np.float64)
        )
        bounds[position] = DomainBounds.from_training(values)
    return bounds


def _predict_fold(
    dataset: RosDataset,
    config: RosValueStudyConfig,
) -> pl.DataFrame:
    """Fit RC1 once per group on the study fold and predict the validation season."""
    selection = ros_feature_selection()
    features = tuple(name for name in selection.included if name in dataset.frame.columns)
    candidate = RosHurdleCandidate()
    frames: list[pl.DataFrame] = []
    for preset in config.scoring_presets:
        for position in config.positions:
            group = (pl.col("position") == position) & (pl.col("scoring_preset") == preset)
            train = dataset.frame.filter(
                pl.col("season").is_in(list(config.fold.train_seasons)) & group,
            )
            validate = dataset.frame.filter(
                (pl.col("season") == config.fold.validation_season)
                & group
                & pl.col("through_week").is_in(list(config.weeks)),
            )
            if train.is_empty() or validate.is_empty():
                continue
            context = RosFitContext(
                fold=config.fold,
                position=position,
                scoring_preset=preset,
                features=features,
                seed=config.seed,
                levels=config.levels,
            )
            block = candidate.fit_predict(train, validate, context)
            frames.append(
                block.keys.select(
                    "season",
                    "through_week",
                    "player_id",
                    "position",
                    "scoring_preset",
                    ROS_TARGET_COLUMN,
                ).with_columns(
                    [
                        pl.Series(name, block.quantiles[:, index], dtype=pl.Float64)
                        for index, name in enumerate(_POINT_COLUMNS)
                    ],
                ),
            )
    if not frames:
        raise ValueError("the value study produced no predictions")
    return pl.concat(frames)


def _simulate(
    projections: pl.DataFrame,
    *,
    preset: Any,
    scoring_preset: str,
    week: int,
    bounds: Mapping[str, DomainBounds],
    rule: RosReplacementRule,
    draws: int,
    seed: int,
    levels: Sequence[float],
    keep_draws: bool = False,
) -> SimulationResult:
    simulation_config = SimulationConfig(
        draws=draws,
        seed=seed,
        model_version=RC1_VERSION,
        scoring_preset=scoring_preset,
        build_id=f"ros:w{week:02d}",
        levels=tuple(levels),
    )
    sampled = sample_points(projections, config=simulation_config, bounds=bounds)
    return simulate_vorp(
        projections,
        preset=preset,
        config=simulation_config,
        bounds=bounds,
        points=sampled,
        keep_draws=keep_draws,
        allocate=_allocate(rule),
    )


def _board(result: SimulationResult, depth: int) -> pl.DataFrame:
    return fair_ranking(result.players, statistic="median_vorp").head(depth)


def _rank_comparison(left: pl.DataFrame, right: pl.DataFrame, *, top: int = 150) -> dict[str, Any]:
    """How far apart two boards are, in the units a reader of the board sees."""
    joined = left.select("player_id", "fair_rank").join(
        right.select("player_id", pl.col("fair_rank").alias("other_rank")),
        on="player_id",
        how="inner",
    )
    if joined.is_empty():
        return {
            "shared_players": 0,
            "fair_rank_spearman": float("nan"),
            "mean_abs_rank_change_top_150": float("nan"),
            "max_abs_rank_change": float("nan"),
            "top_50_overlap": float("nan"),
        }
    ranks = joined.get_column("fair_rank").to_numpy().astype(np.float64)
    other = joined.get_column("other_rank").to_numpy().astype(np.float64)
    inside = ranks <= top
    left_top = set(left.head(50).get_column("player_id").to_list())
    right_top = set(right.head(50).get_column("player_id").to_list())
    return {
        "shared_players": int(joined.height),
        "fair_rank_spearman": spearman(ranks, other),
        "mean_abs_rank_change_top_150": float(np.mean(np.abs(ranks[inside] - other[inside])))
        if bool(np.any(inside))
        else float("nan"),
        "max_abs_rank_change": float(np.max(np.abs(ranks - other))),
        "top_50_overlap": len(left_top & right_top) / 50.0,
    }


def _realized_vorp(
    dataset: RosDataset,
    *,
    season: int,
    week: int,
    scoring_preset: str,
    preset: Any,
    rule: RosReplacementRule,
) -> pl.DataFrame:
    """Actual remaining VORP: the same allocation, fed the outcome instead of a draw."""
    rows = dataset.frame.filter(
        (pl.col("season") == season)
        & (pl.col("through_week") == week)
        & (pl.col("scoring_preset") == scoring_preset),
    ).select("player_id", "position", ROS_TARGET_COLUMN)
    players = [
        PlayerPoints(player_id=str(row[0]), position=str(row[1]), points=float(row[2]))
        for row in rows.iter_rows()
    ]
    if not players:
        return pl.DataFrame(schema={"player_id": pl.String, "actual_vorp": pl.Float64})
    allocation = _allocate(rule)(players, preset)
    ids: list[str] = []
    values: list[float | None] = []
    for player in players:
        baseline = allocation.replacement_points.get(player.position)
        ids.append(player.player_id)
        values.append(None if baseline is None else player.points - baseline)
    return pl.DataFrame(
        {"player_id": ids, "actual_vorp": values},
        schema={"player_id": pl.String, "actual_vorp": pl.Float64},
    )


def _replacement_row(
    result: SimulationResult, rule: RosReplacementRule, week: int
) -> dict[str, Any]:
    return {
        "rule": str(rule),
        "through_week": week,
        "scoring_preset": result.scoring_preset,
        "league_preset_id": result.league_preset_id,
        "replacement": {
            item["position"]: None if item["mean"] is None else round(float(item["mean"]), 3)
            for item in result.replacement
        },
    }


def _replacement_sensitivity(
    dataset: RosDataset,
    predictions: pl.DataFrame,
    league: Any,
    config: RosValueStudyConfig,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Run both replacement rules over identical draws and measure the difference."""
    preset = league.preset(config.league_preset_id)
    rows: list[dict[str, Any]] = []
    boards: dict[str, list[dict[str, Any]]] = {}
    train = dataset.frame.filter(pl.col("season").is_in(list(config.fold.train_seasons)))
    for scoring_preset in config.scoring_presets:
        bounds = _training_bounds(
            train,
            scoring_preset=scoring_preset,
            positions=config.positions,
        )
        for week in config.weeks:
            projections = _projections(predictions, week=week, scoring_preset=scoring_preset)
            if projections.is_empty():
                continue
            results = {
                rule: _simulate(
                    projections,
                    preset=preset,
                    scoring_preset=scoring_preset,
                    week=week,
                    bounds=bounds,
                    rule=rule,
                    draws=config.draws,
                    seed=config.seed,
                    levels=config.levels,
                )
                for rule in RosReplacementRule
            }
            fresh = _board(results[RosReplacementRule.FRESH_ALLOCATION], config.board_depth)
            rostered = _board(results[RosReplacementRule.ROSTERED_DEPTH], config.board_depth)
            comparison = _rank_comparison(fresh, rostered)
            rows.append(
                {
                    "scoring_preset": scoring_preset,
                    "through_week": week,
                    "league_preset_id": config.league_preset_id,
                    **comparison,
                    "replacement_by_rule": {
                        str(rule): {
                            item["position"]: (
                                None if item["mean"] is None else round(float(item["mean"]), 3)
                            )
                            for item in result.replacement
                        }
                        for rule, result in results.items()
                    },
                },
            )
            if scoring_preset == "PPR":
                boards[f"w{week:02d}"] = (
                    rostered.head(25)
                    .select("player_id", "position", "fair_rank", "p50_vorp", "expected_vorp")
                    .to_dicts()
                )
    return rows, boards


def _convergence(
    dataset: RosDataset,
    predictions: pl.DataFrame,
    league: Any,
    config: RosValueStudyConfig,
    *,
    rule: RosReplacementRule,
    penalty: float,
    algorithm: str,
) -> list[ConvergenceEvidence]:
    """The frozen ladder, measured on rest-of-season boards."""
    preset = league.preset(config.league_preset_id)
    train = dataset.frame.filter(pl.col("season").is_in(list(config.fold.train_seasons)))
    evidence: list[ConvergenceEvidence] = []
    scoring_preset = "PPR"
    bounds = _training_bounds(train, scoring_preset=scoring_preset, positions=config.positions)
    for week in config.convergence_weeks:
        projections = _projections(predictions, week=week, scoring_preset=scoring_preset)
        if projections.is_empty():
            continue
        scenario = f"{config.league_preset_id}|{scoring_preset}|w{week:02d}"
        runs: dict[tuple[int, int], SimulationResult] = {}
        for draws in CONVERGENCE_TOLERANCE.draw_ladder:
            for seed in (config.seed, config.alternate_seed):
                runs[(draws, seed)] = _simulate(
                    projections,
                    preset=preset,
                    scoring_preset=scoring_preset,
                    week=week,
                    bounds=bounds,
                    rule=rule,
                    draws=draws,
                    seed=seed,
                    levels=config.levels,
                )
        reference = runs[(CONVERGENCE_TOLERANCE.reference_draws, config.seed)]
        for draws in CONVERGENCE_TOLERANCE.draw_ladder:
            evidence.append(
                _compare(
                    runs[(draws, config.seed)],
                    reference,
                    scenario=scenario,
                    comparison=f"vs {CONVERGENCE_TOLERANCE.reference_draws} draws",
                    draws=draws,
                    config=config,
                    penalty=penalty,
                    algorithm=algorithm,
                ),
            )
            evidence.append(
                _compare(
                    runs[(draws, config.seed)],
                    runs[(draws, config.alternate_seed)],
                    scenario=scenario,
                    comparison="seed to seed",
                    draws=draws,
                    config=config,
                    penalty=penalty,
                    algorithm=algorithm,
                ),
            )
    return evidence


def _compare(
    left: SimulationResult,
    right: SimulationResult,
    *,
    scenario: str,
    comparison: str,
    draws: int,
    config: RosValueStudyConfig,
    penalty: float,
    algorithm: str,
) -> ConvergenceEvidence:
    joined = left.players.join(right.players, on="player_id", how="inner", suffix="_other")

    def gap(column: str) -> tuple[float, float]:
        values = (
            joined.select((pl.col(column) - pl.col(f"{column}_other")).abs().alias("d"))
            .drop_nulls()
            .get_column("d")
            .to_numpy()
            .astype(np.float64)
        )
        if values.size == 0:
            return float("nan"), float("nan")
        return float(np.mean(values)), float(np.quantile(values, 0.99))

    mean_expected, p99_expected = gap("expected_vorp")
    mean_p50, p99_p50 = gap("p50_vorp")
    outer = (
        joined.select(
            (
                (pl.col("p10_vorp") - pl.col("p10_vorp_other")).abs()
                + (pl.col("p90_vorp") - pl.col("p90_vorp_other")).abs()
            ).alias("d")
            / 2.0,
        )
        .drop_nulls()
        .get_column("d")
        .to_numpy()
        .astype(np.float64)
    )
    mean_outer = float(np.mean(outer)) if outer.size else float("nan")
    p99_outer = float(np.quantile(outer, 0.99)) if outer.size else float("nan")

    replacement_gap = max(
        (
            abs(float(a["mean"]) - float(b["mean"]))
            for a, b in zip(left.replacement, right.replacement, strict=False)
            if a["mean"] is not None and b["mean"] is not None
        ),
        default=float("nan"),
    )

    left_board = _board(left, config.board_depth)
    right_board = _board(right, config.board_depth)
    ranks = _rank_comparison(left_board, right_board)
    left_tiers = segment_with(algorithm, left_board, penalty=penalty)
    right_tiers = segment_with(algorithm, right_board, penalty=penalty)
    return ConvergenceEvidence(
        scenario=scenario,
        comparison=comparison,
        draws=draws,
        mean_abs_expected_vorp=mean_expected,
        p99_abs_expected_vorp=p99_expected,
        mean_abs_p50_vorp=mean_p50,
        p99_abs_p50_vorp=p99_p50,
        mean_abs_outer_vorp=mean_outer,
        p99_abs_outer_vorp=p99_outer,
        max_abs_replacement=replacement_gap,
        fair_rank_spearman=float(ranks["fair_rank_spearman"]),
        top_50_overlap=float(ranks["top_50_overlap"]),
        mean_abs_rank_change_top_150=float(ranks["mean_abs_rank_change_top_150"]),
        tier_adjusted_rand=_tier_ari(left_board, left_tiers, right_board, right_tiers),
        tier_count_difference=left_tiers.tier_count - right_tiers.tier_count,
    )


def _tier_ari(
    left_board: pl.DataFrame,
    left: Segmentation,
    right_board: pl.DataFrame,
    right: Segmentation,
) -> float:
    from ffdraft.tiers.stability import adjusted_rand_index

    left_map = dict(zip(left_board.get_column("player_id").to_list(), left.ordinals, strict=True))
    right_map = dict(
        zip(right_board.get_column("player_id").to_list(), right.ordinals, strict=True),
    )
    shared = sorted(set(left_map) & set(right_map))
    if len(shared) < 2:
        return float("nan")
    return adjusted_rand_index(
        [left_map[key] for key in shared],
        [right_map[key] for key in shared],
    )


def _tier_shape(
    dataset: RosDataset,
    predictions: pl.DataFrame,
    league: Any,
    config: RosValueStudyConfig,
    *,
    rule: RosReplacementRule,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Segment every scenario at every penalty of the frozen grid, under both algorithms.

    The simulation is hoisted out of the algorithm loop: both segmentation algorithms read the
    *same* board, so simulating twice would double the study's runtime to produce two identical
    sets of draws - and would also make the two algorithms incomparable if the draws ever
    diverged.
    """
    preset = league.preset(config.league_preset_id)
    train = dataset.frame.filter(pl.col("season").is_in(list(config.fold.train_seasons)))
    rows: list[dict[str, Any]] = []
    stability_inputs: dict[str, Any] = {}
    for scoring_preset in config.scoring_presets:
        bounds = _training_bounds(
            train,
            scoring_preset=scoring_preset,
            positions=config.positions,
        )
        for week in config.weeks:
            projections = _projections(predictions, week=week, scoring_preset=scoring_preset)
            if projections.is_empty():
                continue
            keep = scoring_preset == "PPR" and week == config.convergence_weeks[-1]
            result = _simulate(
                projections,
                preset=preset,
                scoring_preset=scoring_preset,
                week=week,
                bounds=bounds,
                rule=rule,
                draws=config.draws,
                seed=config.seed,
                levels=config.levels,
                keep_draws=keep,
            )
            board = _board(result, config.board_depth)
            for algorithm in (PRIMARY_ALGORITHM, ALTERNATIVE_ALGORITHM):
                for penalty in TIER_SELECTION.penalties:
                    segmentation = segment_with(algorithm, board, penalty=penalty)
                    rows.append(
                        {
                            "algorithm": algorithm,
                            "scoring_preset": scoring_preset,
                            "through_week": week,
                            "penalty": float(penalty),
                            **segmentation.to_dict(),
                        },
                    )
            if keep:
                stability_inputs = {
                    "result": result,
                    "board": board,
                    "boards": {},
                    "scoring_preset": scoring_preset,
                    "through_week": week,
                }
            if stability_inputs and week == stability_inputs.get("through_week"):
                stability_inputs.setdefault("boards", {})[scoring_preset] = board
    return rows, stability_inputs


def run_ros_value_study(
    dataset: RosDataset,
    league: Any,
    *,
    config: RosValueStudyConfig | None = None,
) -> RosValueStudyResult:
    """Run the whole value study and apply the three frozen rules to what it measured."""
    settings = config or RosValueStudyConfig()
    predictions = _predict_fold(dataset, settings)

    sensitivity, boards = _replacement_sensitivity(dataset, predictions, league, settings)
    replacement_decision = decide_replacement(sensitivity)
    rule = RosReplacementRule(replacement_decision.selected)

    shape, stability_inputs = _tier_shape(dataset, predictions, league, settings, rule=rule)
    stability_by_penalty, stability_payload = _bootstrap(stability_inputs, settings)
    tier_decision = select_tier_penalty(
        _candidate_evidence(shape, stability_by_penalty, TIER_SELECTION.penalties),
    )
    penalty = float(tier_decision.selected) if tier_decision.decisive else 1.0

    convergence_evidence = _convergence(
        dataset,
        predictions,
        league,
        settings,
        rule=rule,
        penalty=penalty,
        algorithm=PRIMARY_ALGORITHM,
    )
    convergence_decision = evaluate_convergence(convergence_evidence)

    stability_evidence, stability_detail = _stability_evidence(
        dataset,
        predictions,
        league,
        settings,
        rule=rule,
        penalty=penalty,
        stability=stability_by_penalty.get(penalty),
        stability_inputs=stability_inputs,
    )
    stability_decision = evaluate_tier_stability(stability_evidence)

    checks = _study_checks(
        replacement_decision,
        convergence_decision,
        tier_decision,
        stability_decision,
    )
    return RosValueStudyResult(
        config=settings,
        replacement_sensitivity=tuple(sensitivity),
        replacement_decision=replacement_decision,
        convergence_evidence=tuple(convergence_evidence),
        convergence_decision=convergence_decision,
        tier_shape=tuple(shape),
        tier_decision=tier_decision,
        tier_stability={**stability_payload, **stability_detail},
        stability_decision=stability_decision,
        boards=boards,
        checks=tuple(checks),
    )


def _bootstrap(
    stability_inputs: Mapping[str, Any],
    config: RosValueStudyConfig,
) -> tuple[dict[float, Any], dict[str, Any]]:
    """Resample the simulated seasons and rerun ranking and segmentation."""
    if not stability_inputs:
        return {}, {"measured": False, "reason": "no scenario kept its draws"}
    result: SimulationResult = stability_inputs["result"]
    board: pl.DataFrame = stability_inputs["board"]
    if result.vorp_draws is None or result.point_draws is None:
        return {}, {"measured": False, "reason": "the kept scenario carried no draw matrices"}
    promoted = {
        PRIMARY_ALGORITHM: {
            float(penalty): segment_with(PRIMARY_ALGORITHM, board, penalty=float(penalty))
            for penalty in TIER_SELECTION.penalties
        },
    }
    reports = bootstrap_stability(
        result.players,
        result.vorp_draws,
        result.point_draws,
        promoted=promoted,
        promoted_player_ids=board.get_column("player_id").to_list(),
        statistic="median_vorp",
        board_depth=config.board_depth,
        replicates=config.stability_replicates,
        seed=config.seed,
        levels=config.levels,
    )[PRIMARY_ALGORITHM]
    payload = {
        "measured": True,
        "scenario": {
            "scoring_preset": stability_inputs["scoring_preset"],
            "through_week": stability_inputs["through_week"],
            "league_preset_id": config.league_preset_id,
        },
        "by_penalty": {str(penalty): report.to_dict() for penalty, report in reports.items()},
    }
    return dict(reports), payload


def _nanmean(values: Sequence[Any]) -> float:
    """Mean ignoring NaN, and NaN when there is nothing to average.

    A penalty that puts the whole board in one tier has no boundary effect size at all; the
    frozen rule reads that as "could not be measured" and refuses the penalty, so NaN is the
    intended answer rather than a defect worth warning about.
    """
    finite = [float(value) for value in values if float(value) == float(value)]
    return float(np.mean(finite)) if finite else float("nan")


def _candidate_evidence(
    shape: Sequence[Mapping[str, Any]],
    stability: Mapping[float, Any],
    penalties: Sequence[float],
) -> list[TierCandidateEvidence]:
    """The frozen penalty rule's inputs, measured on the primary algorithm's boards."""
    evidence: list[TierCandidateEvidence] = []
    for penalty in penalties:
        rows = [
            row
            for row in shape
            if float(row["penalty"]) == float(penalty) and row["algorithm"] == PRIMARY_ALGORITHM
        ]
        if not rows:
            continue
        report = stability.get(float(penalty))
        evidence.append(
            TierCandidateEvidence(
                penalty=float(penalty),
                mean_tier_count=float(np.mean([row["tier_count"] for row in rows])),
                singleton_rate=float(np.mean([row["singleton_rate"] for row in rows])),
                largest_tier_share=float(np.mean([row["largest_tier_share"] for row in rows])),
                mean_boundary_effect_size=_nanmean(
                    [row["mean_boundary_effect_size"] for row in rows],
                ),
                median_within_tier_effect_size=_nanmean(
                    [row["median_within_tier_effect_size"] for row in rows],
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


def _stability_evidence(
    dataset: RosDataset,
    predictions: pl.DataFrame,
    league: Any,
    config: RosValueStudyConfig,
    *,
    rule: RosReplacementRule,
    penalty: float,
    stability: Any,
    stability_inputs: Mapping[str, Any],
) -> tuple[TierStabilityEvidence, dict[str, Any]]:
    """Monotonicity against realized value, and agreement between scoring presets."""
    preset = league.preset(config.league_preset_id)
    train = dataset.frame.filter(pl.col("season").is_in(list(config.fold.train_seasons)))
    week = int(stability_inputs.get("through_week", config.weeks[-1]))

    # The boards were already simulated while the tier shape was measured; re-simulating them
    # here would be several minutes of identical draws.
    cached: Mapping[str, pl.DataFrame] = stability_inputs.get("boards", {})
    boards: dict[str, tuple[pl.DataFrame, Segmentation]] = {}
    for scoring_preset in config.scoring_presets:
        board = cached.get(scoring_preset)
        if board is None:
            projections = _projections(predictions, week=week, scoring_preset=scoring_preset)
            if projections.is_empty():
                continue
            bounds = _training_bounds(
                train,
                scoring_preset=scoring_preset,
                positions=config.positions,
            )
            board = _board(
                _simulate(
                    projections,
                    preset=preset,
                    scoring_preset=scoring_preset,
                    week=week,
                    bounds=bounds,
                    rule=rule,
                    draws=config.draws,
                    seed=config.seed,
                    levels=config.levels,
                ),
                config.board_depth,
            )
        boards[scoring_preset] = (
            board,
            segment_with(PRIMARY_ALGORITHM, board, penalty=penalty),
        )

    monotonic = float("nan")
    monotone_detail: dict[str, Any] = {}
    if "PPR" in boards:
        board, segmentation = boards["PPR"]
        realized = _realized_vorp(
            dataset,
            season=config.fold.validation_season,
            week=week,
            scoring_preset="PPR",
            preset=preset,
            rule=rule,
        )
        monotone_detail = _monotonicity(board, segmentation, realized)
        monotonic = float(monotone_detail["monotonic_pair_share"])

    cross = float("nan")
    if "STD" in boards and "PPR" in boards:
        cross = _tier_ari(
            boards["STD"][0],
            boards["STD"][1],
            boards["PPR"][0],
            boards["PPR"][1],
        )

    evidence = TierStabilityEvidence(
        bootstrap_adjusted_rand=(
            float(stability.adjusted_rand) if stability is not None else float("nan")
        ),
        boundary_agreement=(
            float(stability.boundary_agreement) if stability is not None else float("nan")
        ),
        singleton_rate=(float(stability.singleton_rate) if stability is not None else float("nan")),
        tier_count_cv=(float(stability.tier_count_cv) if stability is not None else float("nan")),
        monotonic_pair_share=monotonic,
        cross_preset_adjusted_rand=cross,
    )
    detail = {
        "selected_penalty": penalty,
        "monotonicity": monotone_detail,
        "cross_preset_adjusted_rand": cross,
        "week": week,
    }
    return evidence, detail


def _monotonicity(
    board: pl.DataFrame,
    segmentation: Segmentation,
    realized: pl.DataFrame,
) -> dict[str, Any]:
    """Does realized remaining VORP fall as the tier ordinal grows?"""
    joined = board.with_columns(
        pl.Series("tier_ordinal", list(segmentation.ordinals), dtype=pl.Int32),
    ).join(realized, on="player_id", how="left")
    grouped = (
        joined.filter(pl.col("actual_vorp").is_not_null())
        .group_by("tier_ordinal")
        .agg(pl.col("actual_vorp").mean().alias("mean_actual_vorp"), pl.len().alias("players"))
        .sort("tier_ordinal")
    )
    values = grouped.get_column("mean_actual_vorp").to_list()
    pairs = list(zip(values, values[1:], strict=False))
    monotone = [bool(later <= earlier) for earlier, later in pairs]
    return {
        "tiers": grouped.height,
        "adjacent_pairs": len(pairs),
        "monotonic_pairs": int(sum(monotone)),
        "monotonic_pair_share": float(np.mean(monotone)) if monotone else float("nan"),
        "mean_actual_vorp_by_tier": grouped.to_dicts(),
    }


def _study_checks(
    replacement: Decision,
    convergence: Decision,
    tiers: Decision,
    stability: Decision,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = [
        QualityCheck.ok(
            "ros_value.replacement_rule",
            stage="ros_value",
            message="the rest-of-season replacement interpretation, chosen by a frozen rule",
            observed=f"{replacement.selected}: {'; '.join(replacement.reasons)}",
        ),
    ]
    checks.append(
        QualityCheck.ok(
            "ros_value.convergence",
            stage="ros_value",
            message="Monte Carlo draw count under the frozen tolerance",
            observed=f"{convergence.selected}; decisive={convergence.decisive}",
        )
        if convergence.decisive
        else QualityCheck.fail(
            "ros_value.convergence_not_reached",
            stage="ros_value",
            message="no draw count in the frozen ladder met every convergence tolerance",
            observed="; ".join(convergence.failures[:4]) or "no qualifying count",
            expected=f"a qualifying count in {list(CONVERGENCE_TOLERANCE.draw_ladder)}",
            severity=Severity.WARNING,
        ),
    )
    checks.append(
        QualityCheck.ok(
            "ros_value.tier_penalty",
            stage="ros_value",
            message="tier penalty selected by the frozen rule",
            observed=f"{tiers.selected}; decisive={tiers.decisive}",
        ),
    )
    checks.append(
        QualityCheck.ok(
            "ros_value.tier_stability",
            stage="ros_value",
            message="the promoted segmentation cleared the frozen stability gate",
            observed="; ".join(stability.reasons),
        )
        if stability.decisive
        else QualityCheck.fail(
            "ros_value.tier_stability_failed",
            stage="ros_value",
            message=(
                "the rest-of-season segmentation did not clear the frozen stability gate; "
                "boundaries must be presented as provisional wherever they are shown"
            ),
            observed="; ".join(stability.failures),
            expected="every clause of phase4_tier_stability_v1",
            severity=Severity.WARNING,
        ),
    )
    return checks
