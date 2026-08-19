"""Tier stability: does the segmentation survive resampling?

A tier board that rearranges itself when the simulation is resampled is a drawing, not a
finding, and `docs/MODELING.md` section 14.5 makes measuring that a promotion requirement.

The resampling unit is the **simulated season**, not the player. The tiers are a function of
the Monte Carlo VORP distribution, so the honest question is "how much of this board is a
property of the model and how much is a property of these particular draws?" A bootstrap
over the draw axis answers exactly that: resample draw indices with replacement, recompute
every player's VORP summary from the resampled draws, re-rank the board, re-segment it, and
compare. Resampling players instead would ask a different and less relevant question, since
the board's membership is not in doubt.

Four things are measured, all of them named in the frozen ``phase4_tier_stability_v1`` gate:

* **membership similarity** - the adjusted Rand index between the promoted partition and
  each replicate's, chance-corrected so that a board with three huge tiers cannot score well
  by accident;
* **boundary agreement** - the share of promoted boundaries that a majority of replicates
  also place, which is the diagnostic a tooltip could eventually expose;
* **singleton rate and tier-count dispersion** - whether the number of tiers is a finding or
  a coin flip;
* **boundary frequency by rank region** - where on the board the segmentation is confident.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.simulation.vorp import fair_ranking, quantile_column_names
from ffdraft.tiers.segmentation import Segmentation, segment_board

__all__ = [
    "DEFAULT_BOOTSTRAP_REPLICATES",
    "StabilityReport",
    "adjusted_rand_index",
    "bootstrap_stability",
    "summarise_from_draws",
]

Floats = NDArray[np.float64]

#: Enough replicates for a stable index without a long runtime. Recorded in every report.
DEFAULT_BOOTSTRAP_REPLICATES = 200


def adjusted_rand_index(left: Sequence[int], right: Sequence[int]) -> float:
    """Chance-corrected agreement between two partitions of the same items.

    Written here rather than imported so the tie and edge conventions are the project's own
    (ADR-024). Returns 1.0 for identical partitions and about 0.0 for independent ones; the
    degenerate case where both partitions are a single block is defined as 1.0, because two
    identical partitions agreeing completely is agreement even when it is uninformative.
    """
    a = np.asarray(left, dtype=np.int64)
    b = np.asarray(right, dtype=np.int64)
    if a.size != b.size:
        raise ValueError("partitions must cover the same items")
    if a.size == 0:
        return float("nan")
    _, a_codes = np.unique(a, return_inverse=True)
    _, b_codes = np.unique(b, return_inverse=True)
    table = np.zeros((a_codes.max() + 1, b_codes.max() + 1), dtype=np.int64)
    np.add.at(table, (a_codes, b_codes), 1)

    def pairs(counts: NDArray[np.int64]) -> float:
        return float(np.sum(counts * (counts - 1) / 2.0))

    index = pairs(table)
    expected_a = pairs(table.sum(axis=1))
    expected_b = pairs(table.sum(axis=0))
    total = float(a.size * (a.size - 1) / 2.0)
    if total == 0.0:
        return float("nan")
    expected = expected_a * expected_b / total
    maximum = (expected_a + expected_b) / 2.0
    if maximum == expected:
        return 1.0
    return float((index - expected) / (maximum - expected))


def _quantiles(matrix: Floats, levels: Sequence[float]) -> tuple[Floats, Floats]:
    """Quantiles and mean, taking the fast path when nothing is missing.

    ``nanquantile`` copies and masks before it partitions, which roughly doubles the cost of
    the bootstrap's hot loop. A full pool has no missing VORP at all - a null only appears
    when a position's whole pool was consumed by starting slots - so the check is cheap and
    almost always lets the plain path run.
    """
    level_list = list(levels)
    if np.isnan(matrix).any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanquantile(matrix, level_list, axis=1).T, np.nanmean(matrix, axis=1)
    return np.quantile(matrix, level_list, axis=1).T, np.mean(matrix, axis=1)


def summarise_from_draws(
    players: pl.DataFrame,
    vorp_draws: Floats,
    point_draws: Floats,
    *,
    columns: NDArray[np.int64] | Sequence[int] | None = None,
    levels: Sequence[float] = QUANTILE_LEVELS,
    point_levels: Sequence[float] | None = None,
) -> pl.DataFrame:
    """Rebuild the per-player VORP summary from a subset of simulation draws.

    ``columns`` selects draw indices, with replacement, which is what makes a bootstrap
    replicate. Passing ``None`` recomputes the summary over every draw, which must reproduce
    the original simulation exactly - a property the test suite asserts.

    ``point_levels`` narrows which *point* quantiles are recomputed. The ranking tie-break
    reads only P50 points and the segmentation reads only VORP, so a bootstrap replicate can
    skip four of the five and halve its quantile work; the default recomputes all of them.
    """
    index = np.arange(vorp_draws.shape[1]) if columns is None else np.asarray(columns, dtype=int)
    vorp = vorp_draws[:, index]
    points = point_draws[:, index]
    level_list = list(levels)
    point_list = list(point_levels if point_levels is not None else levels)
    vorp_quantiles, expected_vorp = _quantiles(vorp, level_list)
    point_quantiles, expected_points = _quantiles(points, point_list)
    frame = players.select(
        "player_id", "position", "league_preset_id", "scoring_preset"
    ).with_columns(
        pl.Series("expected_points", expected_points, dtype=pl.Float64),
        *[
            pl.Series(name, point_quantiles[:, position], dtype=pl.Float64)
            for position, name in enumerate(quantile_column_names("points", point_list))
        ],
        pl.Series("expected_vorp", expected_vorp, dtype=pl.Float64),
        *[
            pl.Series(name, vorp_quantiles[:, position], dtype=pl.Float64)
            for position, name in enumerate(quantile_column_names("vorp", level_list))
        ],
    )
    return frame.with_columns((pl.col("p75_vorp") - pl.col("p25_vorp")).alias("uncertainty"))


@dataclass(frozen=True)
class StabilityReport:
    """Everything the frozen stability gate reads, plus the diagnostics behind it."""

    replicates: int
    adjusted_rand: float
    boundary_agreement: float
    singleton_rate: float
    tier_count_cv: float
    tier_counts: tuple[int, ...]
    boundary_frequency: Mapping[int, float]
    boundary_frequency_by_region: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "replicates": self.replicates,
            "bootstrap_adjusted_rand": self.adjusted_rand,
            "boundary_agreement": self.boundary_agreement,
            "singleton_rate": self.singleton_rate,
            "tier_count_cv": self.tier_count_cv,
            "tier_count_distribution": _histogram(self.tier_counts),
            "boundary_frequency": {str(k): v for k, v in sorted(self.boundary_frequency.items())},
            "boundary_frequency_by_region": dict(self.boundary_frequency_by_region),
        }


def _histogram(values: Sequence[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def _region(position: int, depth: int) -> str:
    """Which part of the board a boundary sits in, in draft terms rather than percentiles."""
    if position <= 24:
        return "1-24"
    if position <= 60:
        return "25-60"
    if position <= 120:
        return "61-120"
    if position <= 200:
        return "121-200"
    return f"201-{depth}"


def bootstrap_stability(
    players: pl.DataFrame,
    vorp_draws: Floats,
    point_draws: Floats,
    *,
    promoted: Mapping[str, Mapping[float, Segmentation]],
    promoted_player_ids: Sequence[str],
    statistic: str,
    board_depth: int,
    segmenters: Mapping[str, Callable[[pl.DataFrame, float], Segmentation]] | None = None,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int,
    levels: Sequence[float] = QUANTILE_LEVELS,
) -> dict[str, dict[float, StabilityReport]]:
    """Resample the simulated seasons and rerun the whole ranking-and-segmentation pipeline.

    Every algorithm and every penalty in ``promoted`` is evaluated against the **same**
    replicates. That is not only fair, it is most of the runtime saved: recomputing each
    player's VORP summary from ten thousand resampled draws costs seconds, and segmenting the
    resulting board costs milliseconds, so the expensive step is shared and the cheap one is
    repeated.

    Each replicate re-ranks the board as well as re-segmenting it: a boundary that only
    survives when the fair ranks are held fixed has not been shown to be stable, since the
    ranking comes from the same draws.
    """
    resolved: dict[str, Callable[[pl.DataFrame, float], Segmentation]] = dict(segmenters or {})
    for algorithm in promoted:
        resolved.setdefault(
            algorithm,
            lambda board, penalty: segment_board(board, penalty=penalty),
        )
    generator = np.random.default_rng(seed)
    draws = vorp_draws.shape[1]
    promoted_index = {player_id: index for index, player_id in enumerate(promoted_player_ids)}
    promoted_ordinals = {
        algorithm: {
            penalty: dict(zip(promoted_player_ids, segmentation.ordinals, strict=True))
            for penalty, segmentation in by_penalty.items()
        }
        for algorithm, by_penalty in promoted.items()
    }

    keys = [(algorithm, penalty) for algorithm, by in promoted.items() for penalty in by]
    rand_scores: dict[tuple[str, float], list[float]] = {key: [] for key in keys}
    tier_counts: dict[tuple[str, float], list[int]] = {key: [] for key in keys}
    singleton_rates: dict[tuple[str, float], list[float]] = {key: [] for key in keys}
    boundary_hits: dict[tuple[str, float], dict[int, int]] = {key: {} for key in keys}

    for _ in range(replicates):
        columns: NDArray[np.int64] = np.asarray(
            generator.integers(0, draws, size=draws),
            dtype=np.int64,
        )
        summary = summarise_from_draws(
            players,
            vorp_draws,
            point_draws,
            columns=columns,
            levels=levels,
            point_levels=(0.50,),
        )
        ranked = fair_ranking(summary, statistic=statistic).head(board_depth)
        replicate_ids = ranked.get_column("player_id").to_list()
        for algorithm, penalty in keys:
            segmentation = resolved[algorithm](ranked, penalty)
            key = (algorithm, penalty)
            tier_counts[key].append(segmentation.tier_count)
            singleton_rates[key].append(segmentation.singleton_rate)
            replicate_ordinals = dict(zip(replicate_ids, segmentation.ordinals, strict=True))
            shared = [pid for pid in promoted_player_ids if pid in replicate_ordinals]
            if len(shared) > 1:
                rand_scores[key].append(
                    adjusted_rand_index(
                        [promoted_ordinals[algorithm][penalty][pid] for pid in shared],
                        [replicate_ordinals[pid] for pid in shared],
                    ),
                )
            for index in segmentation.boundaries:
                position = promoted_index.get(replicate_ids[index])
                if position is not None:
                    boundary_hits[key][position] = boundary_hits[key].get(position, 0) + 1

    reports: dict[str, dict[float, StabilityReport]] = {algorithm: {} for algorithm in promoted}
    for algorithm, by_penalty in promoted.items():
        for penalty, segmentation in by_penalty.items():
            key = (algorithm, penalty)
            frequency = {
                position: hits / float(replicates)
                for position, hits in sorted(boundary_hits[key].items())
            }
            promoted_boundaries = list(segmentation.boundaries)
            agreement = (
                float(np.mean([frequency.get(index, 0.0) >= 0.5 for index in promoted_boundaries]))
                if promoted_boundaries
                else float("nan")
            )
            counts = np.asarray(tier_counts[key], dtype=np.float64)
            cv = (
                float(np.std(counts) / np.mean(counts))
                if counts.size and np.mean(counts)
                else float("nan")
            )
            by_region: dict[str, list[float]] = {}
            for position, value in frequency.items():
                by_region.setdefault(_region(position + 1, board_depth), []).append(value)
            reports[algorithm][penalty] = StabilityReport(
                replicates=replicates,
                adjusted_rand=(
                    float(np.mean(rand_scores[key])) if rand_scores[key] else float("nan")
                ),
                boundary_agreement=agreement,
                singleton_rate=(
                    float(np.mean(singleton_rates[key])) if singleton_rates[key] else float("nan")
                ),
                tier_count_cv=cv,
                tier_counts=tuple(tier_counts[key]),
                boundary_frequency=frequency,
                boundary_frequency_by_region={
                    region: float(np.mean(values)) for region, values in sorted(by_region.items())
                },
            )
    return reports
