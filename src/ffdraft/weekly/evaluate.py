"""The weekly start/sit evaluation: rolling-origin folds, the start/sit metrics, the verdict.

Everything this module decides was declared in :mod:`ffdraft.weekly.frozen` before it ran.
It only measures.

**Folds.** Expanding window from 2017. Development folds score 2020-2024 one at a time, each
trained on every earlier season; 2025 is sealed and a development run physically does not
hold its rows (:func:`development_frame`). The final evaluation trains on 2017-2024 and scores
2025 once, behind its own confirmation token.

**The start/sit metrics.** For each week, scoring preset and position, the *decision pool* is
the top ``DECISION_POOL_DEPTH`` players by the neutral B0 point — the same pool for every
model, so no model picks its own exam. Every pair in the pool is one start/sit question:

* **accuracy**: the higher median outscored the lower (a tied median scores half);
* **Brier**: ``(P(A > B) - outcome)^2`` with ``outcome`` 1, 0, or 0.5 for a tie;
* **calibration**: pairs binned by the probability given to the favourite, against how often
  the favourite won — the table the page quotes.

**The bootstrap** resamples whole weeks (``season, target_week``) with replacement, because
the pairs inside one week share players and are anything but independent.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.modeling.preprocessing import scalar_float
from ffdraft.weekly.baselines import fit_baseline
from ffdraft.weekly.dataset import TARGET_COLUMN
from ffdraft.weekly.distribution import grids_from_matrix, pairwise_matrix
from ffdraft.weekly.frozen import (
    BASELINE_IDS,
    DECISION_POOL_DEPTH,
    PROMOTION_RULE,
    WEEKLY_CANDIDATE_VERSION,
    WEEKLY_DEVELOPMENT_SEASONS,
    WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN,
    WEEKLY_POSITIONS,
    WEEKLY_QUANTILE_LEVELS,
    WEEKLY_SEALED_SEASON,
    WEEKLY_SEED,
    WEEKLY_TRAIN_START_SEASON,
    WeeklySpec,
)
from ffdraft.weekly.model import WeeklyModel, fit_weekly_model

__all__ = [
    "CANDIDATE_ID",
    "FoldResult",
    "WeeklyFinalEvalAuthorization",
    "development_frame",
    "evaluate_fold",
    "pinball",
    "run_weekly_experiment",
    "verdict",
]

Floats = NDArray[np.float64]

CANDIDATE_ID = WEEKLY_CANDIDATE_VERSION
MODEL_IDS: tuple[str, ...] = (CANDIDATE_ID, *BASELINE_IDS)

#: Favourite-probability bins for the published calibration table.
CALIBRATION_EDGES: tuple[float, ...] = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0)


class WeeklyFinalEvalAuthorization:
    """Proof the weekly sealed season was opened on purpose, with a reason."""

    __slots__ = ("confirmation", "reason")

    def __init__(self, confirmation: str, reason: str) -> None:
        if confirmation != WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN:
            raise HoldoutSealError(
                "weekly final evaluation requires the exact confirmation token "
                f"{WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN!r}",
            )
        if not reason.strip():
            raise HoldoutSealError("weekly final evaluation requires a recorded reason")
        self.confirmation = confirmation
        self.reason = reason


def development_frame(
    frame: pl.DataFrame,
    *,
    authorization: WeeklyFinalEvalAuthorization | None = None,
) -> pl.DataFrame:
    """The rows a run may hold. The sealed season is removed unless authorized."""
    scoped = frame.filter(pl.col("season") >= WEEKLY_TRAIN_START_SEASON)
    if authorization is not None:
        return scoped
    return scoped.filter(pl.col("season") < WEEKLY_SEALED_SEASON)


def pinball(actual: Floats, quantiles: Floats, levels: Sequence[float]) -> Floats:
    """Per-row pinball loss averaged over ``levels``."""
    diff = actual[:, None] - quantiles
    taus = np.asarray(levels, dtype=np.float64)[None, :]
    return np.mean(np.maximum(taus * diff, (taus - 1.0) * diff), axis=1)


@dataclass
class PairSet:
    """Every scored pair from one model, flattened, with its week cluster."""

    probability: list[Floats] = field(default_factory=list)
    correct: list[Floats] = field(default_factory=list)
    outcome: list[Floats] = field(default_factory=list)
    cluster: list[NDArray[np.int64]] = field(default_factory=list)
    position: list[NDArray[np.str_]] = field(default_factory=list)

    def arrays(self) -> dict[str, Any]:
        if not self.probability:
            empty = np.zeros(0, dtype=np.float64)
            return {
                "probability": empty,
                "correct": empty,
                "outcome": empty,
                "cluster": np.zeros(0, dtype=np.int64),
                "position": np.zeros(0, dtype=str),
            }
        return {
            "probability": np.concatenate(self.probability),
            "correct": np.concatenate(self.correct),
            "outcome": np.concatenate(self.outcome),
            "cluster": np.concatenate(self.cluster),
            "position": np.concatenate(self.position),
        }


@dataclass
class FoldResult:
    season: int
    train_seasons: tuple[int, ...]
    rows: pl.DataFrame
    pairs: dict[str, dict[str, Any]]
    model: WeeklyModel | None = None


def _pool_pairs(
    frame: pl.DataFrame,
    predictions: Mapping[str, Floats],
    b0_points: Floats,
    *,
    season: int,
) -> dict[str, PairSet]:
    pairs = {model_id: PairSet() for model_id in predictions}
    indexed = frame.with_row_index("_row").with_columns(pl.Series("_b0", b0_points))
    grids = {
        model_id: grids_from_matrix(np.nan_to_num(matrix, nan=0.0))
        for model_id, matrix in predictions.items()
    }
    medians = {
        model_id: matrix[:, WEEKLY_QUANTILE_LEVELS.index(0.5)]
        for model_id, matrix in predictions.items()
    }
    # Groups in key order and a stable sort: pair order fixes float summation order, and a
    # tie in B0 must break the same way every run (byte-identical reports).
    groups = sorted(
        indexed.group_by("target_week", "scoring_preset", "position"),
        key=lambda item: tuple(str(part) for part in item[0]),
    )
    for key, block in groups:
        week, _, position = key
        depth = int(DECISION_POOL_DEPTH[str(position)])
        pool = block.sort("_b0", descending=True, maintain_order=True).head(depth)
        if pool.height < 2:
            continue
        rows = pool.get_column("_row").to_numpy()
        actual = pool.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
        upper_i, upper_j = np.triu_indices(rows.shape[0], k=1)
        outcome = np.where(
            actual[upper_i] > actual[upper_j],
            1.0,
            np.where(actual[upper_i] < actual[upper_j], 0.0, 0.5),
        )
        cluster = np.full(upper_i.shape[0], season * 100 + int(str(week)), dtype=np.int64)
        for model_id in predictions:
            matrix = pairwise_matrix(grids[model_id][rows])
            probability = matrix[upper_i, upper_j]
            median = medians[model_id][rows]
            call = np.where(
                median[upper_i] > median[upper_j],
                1.0,
                np.where(median[upper_i] < median[upper_j], 0.0, 0.5),
            )
            correct = np.where(outcome == 0.5, np.nan, 1.0 - np.abs(call - outcome))
            pairs[model_id].probability.append(probability)
            pairs[model_id].correct.append(correct)
            pairs[model_id].outcome.append(outcome)
            pairs[model_id].cluster.append(cluster)
            pairs[model_id].position.append(np.full(upper_i.shape[0], str(position)))
    return pairs


def evaluate_fold(
    frame: pl.DataFrame,
    *,
    season: int,
    spec: WeeklySpec | None = None,
    keep_model: bool = False,
) -> FoldResult:
    """Fit every model on seasons before ``season`` and score ``season``."""
    train = frame.filter(
        (pl.col("season") >= WEEKLY_TRAIN_START_SEASON) & (pl.col("season") < season),
    )
    valid = frame.filter(pl.col("season") == season)
    if train.is_empty() or valid.is_empty():
        raise ValueError(f"fold {season} has no training or no validation rows")

    predictions: dict[str, Floats] = {}
    baselines = {baseline_id: fit_baseline(baseline_id, train) for baseline_id in BASELINE_IDS}
    for baseline_id, baseline in baselines.items():
        predictions[baseline_id] = baseline.predict(valid)
    model = fit_weekly_model(train, spec=spec)
    predictions[CANDIDATE_ID] = model.predict(valid)

    actual = valid.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    levels = list(WEEKLY_QUANTILE_LEVELS)
    columns: dict[str, Any] = {}
    for model_id, matrix in predictions.items():
        clean = np.nan_to_num(matrix, nan=0.0)
        columns[f"{model_id}__pinball"] = pinball(actual, clean, levels)
        columns[f"{model_id}__median"] = clean[:, levels.index(0.5)]
        columns[f"{model_id}__in80"] = (
            (actual >= clean[:, levels.index(0.1)]) & (actual <= clean[:, levels.index(0.9)])
        ).astype(np.float64)
        columns[f"{model_id}__in50"] = (
            (actual >= clean[:, levels.index(0.25)]) & (actual <= clean[:, levels.index(0.75)])
        ).astype(np.float64)
        for index, level in enumerate(levels):
            columns[f"{model_id}__below_{index}"] = (actual <= clean[:, index]).astype(
                np.float64,
            )
            del level
    rows = valid.select(
        "season",
        "target_week",
        "player_id",
        "position",
        "scoring_preset",
        TARGET_COLUMN,
    ).with_columns([pl.Series(name, values) for name, values in columns.items()])
    for index, level in enumerate(levels):
        rows = rows.with_columns(
            pl.Series(f"{CANDIDATE_ID}__q{index}", predictions[CANDIDATE_ID][:, index]),
        )
        del level

    b0_points = baselines["b0_season_rate"].point(valid)
    pair_sets = _pool_pairs(valid, predictions, b0_points, season=season)
    return FoldResult(
        season=season,
        train_seasons=tuple(sorted({int(v) for v in train.get_column("season").unique()})),
        rows=rows,
        pairs={model_id: pair_set.arrays() for model_id, pair_set in pair_sets.items()},
        model=model if keep_model else None,
    )


# ---------------------------------------------------------------------- summarising


def _macro_pinball(rows: pl.DataFrame, model_id: str) -> float:
    cells = rows.group_by("position", "scoring_preset", maintain_order=True).agg(
        pl.col(f"{model_id}__pinball").mean().alias("value"),
    )
    return scalar_float(cells.get_column("value").mean(), math.nan)


def _pair_metrics(pairs: Mapping[str, Any]) -> dict[str, float]:
    correct = pairs["correct"]
    decided = correct[~np.isnan(correct)]
    probability = pairs["probability"]
    outcome = pairs["outcome"]
    return {
        "pairs": int(probability.shape[0]),
        "accuracy": float(np.mean(decided)) if decided.size else math.nan,
        "brier": float(np.mean((probability - outcome) ** 2)) if probability.size else math.nan,
    }


def summarise_rows(rows: pl.DataFrame) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for model_id in MODEL_IDS:
        summary[model_id] = {
            "pinball": _macro_pinball(rows, model_id),
            "mae_median": scalar_float(
                (rows.get_column(f"{model_id}__median") - rows.get_column(TARGET_COLUMN))
                .abs()
                .mean(),
                math.nan,
            ),
            "coverage_80": scalar_float(rows.get_column(f"{model_id}__in80").mean(), math.nan),
            "coverage_50": scalar_float(rows.get_column(f"{model_id}__in50").mean(), math.nan),
            "level_coverage": [
                scalar_float(rows.get_column(f"{model_id}__below_{index}").mean(), math.nan)
                for index in range(len(WEEKLY_QUANTILE_LEVELS))
            ],
        }
    return summary


def concat_pairs(parts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(parts)
    return {key: np.concatenate([item[key] for item in items]) for key in items[0]}


def bootstrap_accuracy_difference(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    replicates: int,
    level: float,
    seed: int = WEEKLY_SEED,
) -> dict[str, float]:
    """Week-clustered bootstrap of (candidate accuracy - baseline accuracy)."""
    clusters = candidate["cluster"]
    unique, inverse = np.unique(clusters, return_inverse=True)
    decided = ~np.isnan(candidate["correct"]) & ~np.isnan(baseline["correct"])
    cand = np.where(decided, candidate["correct"], 0.0)
    base = np.where(decided, baseline["correct"], 0.0)
    count = np.bincount(inverse, weights=decided.astype(np.float64), minlength=unique.shape[0])
    cand_sum = np.bincount(inverse, weights=cand, minlength=unique.shape[0])
    base_sum = np.bincount(inverse, weights=base, minlength=unique.shape[0])
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        pick = rng.integers(0, unique.shape[0], unique.shape[0])
        total = count[pick].sum()
        draws[index] = (cand_sum[pick].sum() - base_sum[pick].sum()) / total
    tail = (1.0 - level) / 2.0
    point = (cand_sum.sum() - base_sum.sum()) / count.sum()
    return {
        "difference": float(point),
        "lower": float(np.quantile(draws, tail)),
        "upper": float(np.quantile(draws, 1.0 - tail)),
        "clusters": int(unique.shape[0]),
        "replicates": replicates,
    }


def calibration_table(pairs: Mapping[str, Any]) -> list[dict[str, float]]:
    """Favourite probability bins against how often the favourite won."""
    probability = pairs["probability"]
    outcome = pairs["outcome"]
    favourite = np.maximum(probability, 1.0 - probability)
    won = np.where(probability >= 0.5, outcome, 1.0 - outcome)
    table: list[dict[str, float]] = []
    for low, high in zip(CALIBRATION_EDGES, CALIBRATION_EDGES[1:], strict=False):
        mask = (favourite >= low) & (favourite < high if high < 1.0 else favourite <= high)
        if not np.any(mask):
            continue
        table.append(
            {
                "low": low,
                "high": high,
                "pairs": int(np.sum(mask)),
                "predicted": float(np.mean(favourite[mask])),
                "observed": float(np.mean(won[mask])),
            },
        )
    return table


def verdict(
    pooled: Mapping[str, Mapping[str, float]],
    by_season: Mapping[int, Mapping[str, Mapping[str, float]]],
    bootstrap: Mapping[str, float] | None,
    *,
    development: bool,
) -> dict[str, Any]:
    """Apply ``weekly_promotion_v1`` to measured numbers. Every clause is reported."""
    rule = PROMOTION_RULE

    def best(metric: str, lower_is_better: bool) -> tuple[str, float]:
        values = {baseline_id: pooled[baseline_id][metric] for baseline_id in BASELINE_IDS}
        chooser = min if lower_is_better else max
        winner = chooser(values, key=lambda key: values[key])
        return winner, values[winner]

    candidate = pooled[CANDIDATE_ID]
    pinball_best = best("pinball", True)
    accuracy_best = best("pair_accuracy", False)
    brier_best = best("pair_brier", True)
    clauses: dict[str, dict[str, Any]] = {
        "pinball_below_best_baseline": {
            "candidate": candidate["pinball"],
            "best_baseline": pinball_best[0],
            "baseline": pinball_best[1],
            "passed": candidate["pinball"] < pinball_best[1],
        },
        "pairwise_accuracy_above_best_baseline": {
            "candidate": candidate["pair_accuracy"],
            "best_baseline": accuracy_best[0],
            "baseline": accuracy_best[1],
            "passed": candidate["pair_accuracy"] > accuracy_best[1]
            and (not development or (bootstrap is not None and bootstrap["lower"] > 0.0)),
            "bootstrap": dict(bootstrap) if bootstrap is not None else None,
        },
        "pairwise_brier_below_best_baseline": {
            "candidate": candidate["pair_brier"],
            "best_baseline": brier_best[0],
            "baseline": brier_best[1],
            "passed": candidate["pair_brier"] < brier_best[1],
        },
        "coverage_80_in_band": {
            "candidate": candidate["coverage_80"],
            "band": list(rule.coverage_80_band),
            "passed": rule.coverage_80_band[0]
            <= candidate["coverage_80"]
            <= rule.coverage_80_band[1],
        },
    }
    if development:
        wins = sum(
            1
            for season_summary in by_season.values()
            if season_summary[CANDIDATE_ID]["pinball"]
            < min(season_summary[b]["pinball"] for b in BASELINE_IDS)
        )
        clauses["pinball_wins_by_fold"] = {
            "wins": wins,
            "folds": len(by_season),
            "minimum": rule.min_pinball_wins,
            "passed": wins >= rule.min_pinball_wins,
        }
        clauses["coverage_50_in_band"] = {
            "candidate": candidate["coverage_50"],
            "band": list(rule.coverage_50_band),
            "passed": rule.coverage_50_band[0]
            <= candidate["coverage_50"]
            <= rule.coverage_50_band[1],
        }
    else:
        clauses = {key: value for key, value in clauses.items() if key in rule.holdout_clauses}
    return {
        "rule": rule.version,
        "stage": "development" if development else "final_holdout",
        "clauses": clauses,
        "passed": all(bool(value["passed"]) for value in clauses.values()),
    }


def run_weekly_experiment(
    frame: pl.DataFrame,
    *,
    seasons: Sequence[int] = WEEKLY_DEVELOPMENT_SEASONS,
    authorization: WeeklyFinalEvalAuthorization | None = None,
    spec: WeeklySpec | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Run the declared folds and return the machine-readable report."""
    development = authorization is None
    scoped = development_frame(frame, authorization=authorization)
    if development and any(season >= WEEKLY_SEALED_SEASON for season in seasons):
        raise HoldoutSealError(
            f"season {WEEKLY_SEALED_SEASON} is the weekly model's sealed holdout; a development "
            "run cannot score it",
        )
    folds: list[FoldResult] = []
    for season in seasons:
        if progress is not None:
            progress(f"fold {season}")
        folds.append(evaluate_fold(scoped, season=season, spec=spec, keep_model=True))

    all_rows = pl.concat([fold.rows for fold in folds], how="vertical_relaxed")
    pooled = summarise_rows(all_rows)
    pooled_pairs = {
        model_id: concat_pairs(fold.pairs[model_id] for fold in folds) for model_id in MODEL_IDS
    }
    for model_id in MODEL_IDS:
        metrics = _pair_metrics(pooled_pairs[model_id])
        pooled[model_id]["pair_accuracy"] = metrics["accuracy"]
        pooled[model_id]["pair_brier"] = metrics["brier"]
        pooled[model_id]["pairs"] = metrics["pairs"]

    by_season: dict[int, dict[str, dict[str, float]]] = {}
    for fold in folds:
        summary = summarise_rows(fold.rows)
        for model_id in MODEL_IDS:
            metrics = _pair_metrics(fold.pairs[model_id])
            summary[model_id]["pair_accuracy"] = metrics["accuracy"]
            summary[model_id]["pair_brier"] = metrics["brier"]
            summary[model_id]["pairs"] = metrics["pairs"]
        by_season[fold.season] = summary

    by_position: dict[str, dict[str, dict[str, float]]] = {}
    for position in WEEKLY_POSITIONS:
        subset = all_rows.filter(pl.col("position") == position)
        summary = summarise_rows(subset)
        for model_id in MODEL_IDS:
            pairs = pooled_pairs[model_id]
            mask = pairs["position"] == position
            metrics = _pair_metrics({key: value[mask] for key, value in pairs.items()})
            summary[model_id]["pair_accuracy"] = metrics["accuracy"]
            summary[model_id]["pair_brier"] = metrics["brier"]
            summary[model_id]["pairs"] = metrics["pairs"]
        by_position[position] = summary

    best_accuracy = max(BASELINE_IDS, key=lambda b: pooled[b]["pair_accuracy"])
    bootstrap = bootstrap_accuracy_difference(
        pooled_pairs[CANDIDATE_ID],
        pooled_pairs[best_accuracy],
        replicates=PROMOTION_RULE.bootstrap_replicates,
        level=PROMOTION_RULE.bootstrap_level,
    )
    decision = verdict(pooled, by_season, bootstrap, development=development)

    diagnostics = {
        "calibration": calibration_table(pooled_pairs[CANDIDATE_ID]),
        "calibration_best_baseline": calibration_table(pooled_pairs[best_accuracy]),
        "crossing_rate": {
            fold.season: {
                key: group.raw_crossing_rate
                for key, group in (fold.model.groups.items() if fold.model else [])
            }
            for fold in folds
        },
        "offsets": {
            fold.season: {
                key: group.offsets
                for key, group in (fold.model.groups.items() if fold.model else [])
            }
            for fold in folds
        },
    }
    return {
        "candidate": CANDIDATE_ID,
        "baselines": list(BASELINE_IDS),
        "folds": [
            {"season": fold.season, "train_seasons": list(fold.train_seasons)} for fold in folds
        ],
        "pooled": pooled,
        "by_season": {str(season): value for season, value in by_season.items()},
        "by_position": by_position,
        "bootstrap_accuracy_vs": best_accuracy,
        "verdict": decision,
        "diagnostics": diagnostics,
        "_rows": all_rows,
        "_pairs": pooled_pairs,
    }
