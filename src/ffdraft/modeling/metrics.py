"""Point, rank and probabilistic metrics, declared before any model was compared.

Every metric here is written against NumPy rather than pulled from a statistics library, so
that tie handling, denominators and edge cases are the project's own documented choices and
are checked against hand-worked examples in the test suite (ADR-024). The test suite also
cross-checks the two correlation coefficients against an independent implementation.

Primary metrics, fixed before the comparison:

* point accuracy — **MAE** of the point prediction (P50 for a quantile model);
* ranking — **Spearman** rank correlation, computed *within* a validation-season x position
  x scoring slice, because ranking a QB against a WR is not a decision anyone makes;
* probabilistic — **mean pinball loss** across the five declared quantiles.

Secondary: RMSE, Kendall tau-b, top-K retrieval, per-quantile pinball, empirical coverage of
the P10-P90 and P25-P75 intervals, interval width, and the raw quantile crossing rate.

Coverage and width are always reported together. An interval wide enough to swallow every
observation is not calibrated, it is uninformative, and reporting only its coverage would
say the opposite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "QUANTILE_LEVELS",
    "TOP_K_BY_POSITION",
    "average_ranks",
    "coverage",
    "crossing_magnitude",
    "crossing_rate",
    "kendall_tau_b",
    "mae",
    "mean_pinball",
    "pinball",
    "rmse",
    "slice_metrics",
    "spearman",
    "top_k_recall",
]

#: The declared predictive quantiles. Every candidate and every baseline emits exactly
#: these, so pinball loss and coverage compare like with like.
QUANTILE_LEVELS: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)

#: Retrieval depth per position for the top-K diagnostic: the number of players a 12-team
#: league starts at that position (`config/league-defaults.yaml`, redraft-12: 1 QB, 2 RB,
#: 2 WR, 1 TE). FLEX is deliberately not spread across RB/WR/TE here - the point is a fixed,
#: interpretable depth, not a simulation.
TOP_K_BY_POSITION: Mapping[str, int] = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}

Floats = NDArray[np.float64]


def _as_float(values: Sequence[float] | NDArray[Any]) -> Floats:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"expected a 1-d array, got shape {array.shape}")
    return array


def mae(actual: Sequence[float] | Floats, predicted: Sequence[float] | Floats) -> float:
    a, p = _as_float(actual), _as_float(predicted)
    if a.size == 0:
        return float("nan")
    return float(np.mean(np.abs(a - p)))


def rmse(actual: Sequence[float] | Floats, predicted: Sequence[float] | Floats) -> float:
    a, p = _as_float(actual), _as_float(predicted)
    if a.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((a - p) ** 2)))


def average_ranks(values: Sequence[float] | Floats) -> Floats:
    """Ranks with ties averaged, 1-based. The building block of both rank statistics."""
    array = _as_float(values)
    n = array.size
    if n == 0:
        return array
    order = np.argsort(array, kind="stable")
    ranks = np.empty(n, dtype=np.float64)
    sorted_values = array[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def _pearson(x: Floats, y: Floats) -> float:
    if x.size < 2:
        return float("nan")
    xc = x - x.mean()
    yc = y - y.mean()
    denominator = float(np.sqrt(float(np.dot(xc, xc)) * float(np.dot(yc, yc))))
    if denominator == 0.0:
        # One side is constant: no ordering information exists, and calling that a
        # correlation of zero would be a claim the data does not support.
        return float("nan")
    return float(np.dot(xc, yc) / denominator)


def spearman(actual: Sequence[float] | Floats, predicted: Sequence[float] | Floats) -> float:
    """Spearman rho: Pearson correlation of average ranks, ties handled by averaging."""
    a, p = _as_float(actual), _as_float(predicted)
    if a.size != p.size:
        raise ValueError("actual and predicted must be the same length")
    return _pearson(average_ranks(a), average_ranks(p))


def kendall_tau_b(
    actual: Sequence[float] | Floats,
    predicted: Sequence[float] | Floats,
) -> float:
    """Kendall tau-b, the tie-corrected variant.

    ``tau_b = (C - D) / sqrt((n0 - n1) * (n0 - n2))`` with ``n0 = n(n-1)/2``, ``n1`` and
    ``n2`` the tie corrections for each side. Pairs are counted directly; validation slices
    here are a few hundred rows, so an explicit O(n^2) count is both fast enough and much
    easier to verify against a hand-worked example than a merge-sort inversion count.
    """
    a, p = _as_float(actual), _as_float(predicted)
    if a.size != p.size:
        raise ValueError("actual and predicted must be the same length")
    n = a.size
    if n < 2:
        return float("nan")
    da = np.sign(a[:, None] - a[None, :])
    dp = np.sign(p[:, None] - p[None, :])
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    products = (da * dp)[upper]
    concordant = float(np.sum(products > 0))
    discordant = float(np.sum(products < 0))
    n0 = n * (n - 1) / 2.0
    n1 = float(np.sum(da[upper] == 0))
    n2 = float(np.sum(dp[upper] == 0))
    denominator = np.sqrt((n0 - n1) * (n0 - n2))
    if denominator == 0.0:
        return float("nan")
    return float((concordant - discordant) / denominator)


def top_k_recall(
    actual: Sequence[float] | Floats,
    predicted: Sequence[float] | Floats,
    k: int,
) -> float:
    """Share of the actual top-K that the prediction's own top-K retrieved.

    Ties are broken by the value's position in the input, which is deterministic because the
    caller sorts the frame. With ``k >= n`` the metric is 1.0 by construction and is
    reported as such rather than suppressed.
    """
    a, p = _as_float(actual), _as_float(predicted)
    if a.size == 0 or k <= 0:
        return float("nan")
    k = min(k, a.size)
    actual_top = set(np.argsort(-a, kind="stable")[:k].tolist())
    predicted_top = set(np.argsort(-p, kind="stable")[:k].tolist())
    return len(actual_top & predicted_top) / float(k)


def pinball(
    actual: Sequence[float] | Floats,
    predicted: Sequence[float] | Floats,
    quantile: float,
) -> float:
    """Mean pinball (quantile) loss at one level."""
    a, p = _as_float(actual), _as_float(predicted)
    if a.size == 0:
        return float("nan")
    delta = a - p
    return float(np.mean(np.maximum(quantile * delta, (quantile - 1.0) * delta)))


def mean_pinball(
    actual: Sequence[float] | Floats,
    quantile_predictions: NDArray[np.float64],
    levels: Sequence[float] = QUANTILE_LEVELS,
) -> float:
    """Pinball loss averaged over the declared quantile levels."""
    a = _as_float(actual)
    matrix = np.asarray(quantile_predictions, dtype=np.float64)
    if matrix.shape != (a.size, len(levels)):
        raise ValueError(
            f"quantile matrix shape {matrix.shape} does not match "
            f"({a.size}, {len(levels)}) implied by the inputs",
        )
    if a.size == 0:
        return float("nan")
    losses = [pinball(a, matrix[:, index], level) for index, level in enumerate(levels)]
    return float(np.mean(losses))


def coverage(
    actual: Sequence[float] | Floats,
    lower: Sequence[float] | Floats,
    upper: Sequence[float] | Floats,
) -> float:
    """Empirical share of observations inside a closed predictive interval."""
    a, lo, hi = _as_float(actual), _as_float(lower), _as_float(upper)
    if a.size == 0:
        return float("nan")
    return float(np.mean((a >= lo) & (a <= hi)))


def crossing_rate(quantile_predictions: NDArray[np.float64]) -> float:
    """Share of rows whose raw quantiles are not non-decreasing across the declared levels.

    Reported for the raw model output. Any monotone repair is applied and reported
    separately, so the defect is visible rather than hidden by the fix.
    """
    matrix = np.asarray(quantile_predictions, dtype=np.float64)
    if matrix.size == 0:
        return float("nan")
    differences = np.diff(matrix, axis=1)
    return float(np.mean(np.any(differences < 0.0, axis=1)))


def crossing_magnitude(quantile_predictions: NDArray[np.float64]) -> float:
    """Mean total size of the crossings, in fantasy points.

    A crossing rate on its own cannot distinguish "these intervals are incoherent" from
    "two adjacent quantiles are both about zero and one landed 0.3 points below the other".
    Reporting the magnitude alongside the rate is what makes the difference legible.
    """
    matrix = np.asarray(quantile_predictions, dtype=np.float64)
    if matrix.size == 0:
        return float("nan")
    differences = np.diff(matrix, axis=1)
    return float(np.mean(np.sum(np.clip(-differences, 0.0, None), axis=1)))


def slice_metrics(
    actual: Sequence[float] | Floats,
    point: Sequence[float] | Floats,
    quantile_predictions: NDArray[np.float64],
    *,
    position: str,
    levels: Sequence[float] = QUANTILE_LEVELS,
    raw_quantiles: NDArray[np.float64] | None = None,
) -> dict[str, Any]:
    """Every declared metric for one validation-season x position x scoring slice."""
    a = _as_float(actual)
    p = _as_float(point)
    matrix = np.asarray(quantile_predictions, dtype=np.float64)
    index = {level: position_index for position_index, level in enumerate(levels)}
    raw = matrix if raw_quantiles is None else np.asarray(raw_quantiles, dtype=np.float64)

    p10, p25, p75, p90 = (matrix[:, index[level]] for level in (0.10, 0.25, 0.75, 0.90))
    metrics: dict[str, Any] = {
        "n": int(a.size),
        "mae": mae(a, p),
        "rmse": rmse(a, p),
        "spearman": spearman(a, p),
        "kendall_tau_b": kendall_tau_b(a, p),
        "top_k": TOP_K_BY_POSITION.get(position, 0),
        "top_k_recall": top_k_recall(a, p, TOP_K_BY_POSITION.get(position, 0)),
        "mean_pinball": mean_pinball(a, matrix, levels),
        "pinball_by_quantile": {
            f"p{int(level * 100):02d}": pinball(a, matrix[:, position_index], level)
            for position_index, level in enumerate(levels)
        },
        "coverage_p10_p90": coverage(a, p10, p90),
        "coverage_p25_p75": coverage(a, p25, p75),
        "mean_width_p10_p90": float(np.mean(p90 - p10)) if a.size else float("nan"),
        "mean_width_p25_p75": float(np.mean(p75 - p25)) if a.size else float("nan"),
        "crossing_rate_raw": crossing_rate(raw),
        "crossing_magnitude_raw": crossing_magnitude(raw),
        "mean_actual": float(np.mean(a)) if a.size else float("nan"),
        "mean_prediction": float(np.mean(p)) if a.size else float("nan"),
    }
    return metrics
