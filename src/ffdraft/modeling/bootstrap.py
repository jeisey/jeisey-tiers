"""Deterministic paired block bootstrap for model-versus-model deltas.

The comparison that matters is *paired*: the candidate and the baseline predicted the same
player-seasons, so bootstrapping them independently would throw away the pairing and inflate
the uncertainty of their difference. Here one resample is drawn per replicate and both
models' predictions for the same rows are carried through it together.

The blocks are the evaluation cells - validation season x position x scoring preset - and
resampling happens *within* a block. Pooling twelve seasons of player-seasons into one urn
and calling them exchangeable would assume away the temporal structure the whole evaluation
design exists to respect; a cell, by contrast, is one season's players competing at one
position under one scoring rule, which is the unit a fantasy decision is actually made over.

Determinism: each cell gets its own index matrix, drawn from a generator seeded by the
experiment seed and a stable hash of the cell key. Replicate ``r`` uses row ``r`` of every
cell's matrix, so the result does not depend on iteration order, cell count or which metrics
were requested.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ffdraft.modeling.metrics import QUANTILE_LEVELS

__all__ = [
    "DEFAULT_REPLICATES",
    "BootstrapDelta",
    "PairedCell",
    "paired_bootstrap",
    "row_pinball_loss",
]

Floats = NDArray[np.float64]

#: Enough for stable development reporting without an unreasonable runtime. Recorded in the
#: report; never varied between the runs a decision compares.
DEFAULT_REPLICATES = 1000

#: The percentile interval reported for every delta.
CONFIDENCE = 0.95


def row_pinball_loss(
    actual: Floats,
    quantiles: Floats,
    levels: Sequence[float] = QUANTILE_LEVELS,
) -> Floats:
    """Per-row pinball loss averaged over the declared levels.

    Reducing the probabilistic metric to one number per row is what lets the bootstrap
    resample it as cheaply as an absolute error, and it is exactly the quantity the cell
    metric averages.
    """
    losses = np.zeros(actual.shape[0], dtype=np.float64)
    for index, level in enumerate(levels):
        delta = actual - quantiles[:, index]
        losses += np.maximum(level * delta, (level - 1.0) * delta)
    return losses / float(len(levels))


@dataclass(frozen=True)
class PairedCell:
    """One evaluation cell with both models' predictions for the same rows."""

    key: str
    actual: Floats
    baseline_point: Floats
    candidate_point: Floats
    baseline_quantiles: Floats
    candidate_quantiles: Floats

    @property
    def size(self) -> int:
        return int(self.actual.size)


@dataclass(frozen=True)
class BootstrapDelta:
    """A paired delta with its percentile interval. Negative is better for a loss metric."""

    metric: str
    lower_is_better: bool
    baseline: float
    candidate: float
    delta: float
    ci_low: float
    ci_high: float
    replicates: int
    seed: int
    share_favouring_candidate: float

    @property
    def significant(self) -> bool:
        """True when the interval excludes zero, i.e. the sign of the delta is resolved."""
        return (self.ci_low > 0.0) or (self.ci_high < 0.0)

    @property
    def favours_candidate(self) -> bool:
        improved = self.delta < 0.0 if self.lower_is_better else self.delta > 0.0
        return improved and self.significant

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "lower_is_better": self.lower_is_better,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "ci_excludes_zero": self.significant,
            "favours_candidate": self.favours_candidate,
            "replicates": self.replicates,
            "seed": self.seed,
            "share_favouring_candidate": self.share_favouring_candidate,
        }


def _cell_seed(base_seed: int, key: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1)


def _indices(cell: PairedCell, *, base_seed: int, replicates: int) -> NDArray[np.int64]:
    generator = np.random.default_rng(_cell_seed(base_seed, cell.key))
    return generator.integers(0, cell.size, size=(replicates, cell.size), dtype=np.int64)


def _average_ranks_2d(values: Floats) -> Floats:
    """Tie-averaged ranks for every row of a 2-d array, vectorized.

    Bootstrap resamples duplicate rows constantly, so ties are the common case rather than
    an edge case, and an ordinal rank would quietly change the statistic being estimated.
    """
    replicates, size = values.shape
    order = np.argsort(values, axis=1, kind="stable")
    ordered = np.take_along_axis(values, order, axis=1)
    starts_group = np.ones_like(ordered, dtype=bool)
    starts_group[:, 1:] = ordered[:, 1:] != ordered[:, :-1]
    group = np.cumsum(starts_group, axis=1) - 1
    flat = (group + np.arange(replicates, dtype=np.int64)[:, None] * size).ravel()
    positions = np.tile(np.arange(1, size + 1, dtype=np.float64), replicates)
    counts = np.bincount(flat, minlength=replicates * size)
    totals = np.bincount(flat, weights=positions, minlength=replicates * size)
    mean_rank = totals / np.maximum(counts, 1)
    ranked_sorted = mean_rank[flat].reshape(replicates, size)
    ranks: Floats = np.empty_like(ranked_sorted)
    np.put_along_axis(ranks, order, ranked_sorted, axis=1)
    return ranks


def _row_spearman(actual: Floats, predicted: Floats) -> Floats:
    """Spearman rho for each row of a paired (replicates, n) pair of matrices."""
    a = _average_ranks_2d(actual)
    p = _average_ranks_2d(predicted)
    a = a - a.mean(axis=1, keepdims=True)
    p = p - p.mean(axis=1, keepdims=True)
    numerator = np.sum(a * p, axis=1)
    denominator = np.sqrt(np.sum(a * a, axis=1) * np.sum(p * p, axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denominator > 0.0, numerator / denominator, np.nan)


def _cell_statistics(
    cell: PairedCell,
    indices: NDArray[np.int64],
    levels: Sequence[float],
) -> dict[str, tuple[Floats, Floats]]:
    """Per-replicate cell metrics for both models, computed on identical resampled rows."""
    baseline_error = np.abs(cell.actual - cell.baseline_point)
    candidate_error = np.abs(cell.actual - cell.candidate_point)
    baseline_pinball = row_pinball_loss(cell.actual, cell.baseline_quantiles, levels)
    candidate_pinball = row_pinball_loss(cell.actual, cell.candidate_quantiles, levels)

    resampled_actual = cell.actual[indices]
    return {
        "mae": (
            baseline_error[indices].mean(axis=1),
            candidate_error[indices].mean(axis=1),
        ),
        "mean_pinball": (
            baseline_pinball[indices].mean(axis=1),
            candidate_pinball[indices].mean(axis=1),
        ),
        "spearman": (
            _row_spearman(resampled_actual, cell.baseline_point[indices]),
            _row_spearman(resampled_actual, cell.candidate_point[indices]),
        ),
    }


#: Which way is better for each supported metric.
LOWER_IS_BETTER: Mapping[str, bool] = {
    "mae": True,
    "mean_pinball": True,
    "spearman": False,
}


def paired_bootstrap(
    cells: Sequence[PairedCell],
    *,
    metrics: Sequence[str] = ("mae", "mean_pinball", "spearman"),
    seed: int,
    replicates: int = DEFAULT_REPLICATES,
    levels: Sequence[float] = QUANTILE_LEVELS,
) -> dict[str, BootstrapDelta]:
    """Macro-aggregated paired deltas with percentile intervals.

    The aggregate is a macro mean across cells, so a 300-row WR cell does not outvote a
    100-row QB cell. Cells whose metric is undefined in a replicate - a constant prediction
    makes Spearman undefined - are dropped from that replicate's mean rather than counted as
    zero.
    """
    if not cells:
        raise ValueError("a paired bootstrap needs at least one evaluation cell")
    per_cell = {
        cell.key: _cell_statistics(
            cell,
            _indices(cell, base_seed=seed, replicates=replicates),
            levels,
        )
        for cell in cells
    }

    results: dict[str, BootstrapDelta] = {}
    tail = (1.0 - CONFIDENCE) / 2.0
    for metric in metrics:
        baseline_matrix = np.vstack([per_cell[cell.key][metric][0] for cell in cells])
        candidate_matrix = np.vstack([per_cell[cell.key][metric][1] for cell in cells])
        with np.errstate(invalid="ignore"):
            baseline_series = np.nanmean(baseline_matrix, axis=0)
            candidate_series = np.nanmean(candidate_matrix, axis=0)
        deltas = candidate_series - baseline_series
        observed = _observed_delta(cells, metric, levels)
        lower_better = LOWER_IS_BETTER[metric]
        favouring = float(np.mean(deltas < 0.0)) if lower_better else float(np.mean(deltas > 0.0))
        results[metric] = BootstrapDelta(
            metric=metric,
            lower_is_better=lower_better,
            baseline=observed[0],
            candidate=observed[1],
            delta=observed[1] - observed[0],
            ci_low=float(np.quantile(deltas, tail)),
            ci_high=float(np.quantile(deltas, 1.0 - tail)),
            replicates=replicates,
            seed=seed,
            share_favouring_candidate=favouring,
        )
    return results


def _observed_delta(
    cells: Sequence[PairedCell],
    metric: str,
    levels: Sequence[float],
) -> tuple[float, float]:
    """The macro metric on the observed data, which the interval is centred on."""
    from ffdraft.modeling.metrics import mae, mean_pinball, spearman

    baseline_values: list[float] = []
    candidate_values: list[float] = []
    for cell in cells:
        if metric == "mae":
            baseline_values.append(mae(cell.actual, cell.baseline_point))
            candidate_values.append(mae(cell.actual, cell.candidate_point))
        elif metric == "mean_pinball":
            baseline_values.append(mean_pinball(cell.actual, cell.baseline_quantiles, levels))
            candidate_values.append(mean_pinball(cell.actual, cell.candidate_quantiles, levels))
        elif metric == "spearman":
            baseline_values.append(spearman(cell.actual, cell.baseline_point))
            candidate_values.append(spearman(cell.actual, cell.candidate_point))
        else:  # pragma: no cover - guarded by LOWER_IS_BETTER
            raise ValueError(f"unsupported bootstrap metric {metric!r}")
    return (
        float(np.nanmean(np.asarray(baseline_values, dtype=np.float64))),
        float(np.nanmean(np.asarray(candidate_values, dtype=np.float64))),
    )
