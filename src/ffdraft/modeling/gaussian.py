"""The standard normal CDF and its inverse, written against NumPy.

ADR-024 keeps SciPy out of production code: the project writes the handful of statistical
primitives it needs, documents the approximation it chose, and pins the result against an
independent implementation in the test suite. Two primitives are needed here, both for the
Gaussian copula that couples Candidate B's availability and performance components:

* :func:`norm_cdf` turns correlated normal draws into the uniforms a quantile function
  consumes;
* :func:`norm_ppf` turns observed probability-integral transforms back into normal scores so
  a single dependence parameter can be estimated from them.

Both are vectorized over NumPy arrays, because the copula evaluates them over
``players x draws`` matrices and a Python-level loop over ``math.erf`` would dominate the
Monte Carlo cost.

Accuracy is far beyond what a copula parameter needs, and the property that matters most
is that the two functions are *mutual inverses*, because the copula's round trip is
``value -> u -> z -> correlated z -> u -> value``. The CDF uses Abramowitz & Stegun 7.1.26
for ``erf``, whose absolute error stays below 1.5e-7. The inverse uses Acklam's rational
approximation followed by one Halley refinement step **against that CDF**, so
``norm_cdf(norm_ppf(p)) == p`` to about 1e-9 by construction - the residual is A&S 7.1.26's
own error near the origin, where the series does not evaluate to exactly zero. Measured against an
independent implementation, ``norm_ppf`` agrees to 2e-5 over ``p`` in [1e-3, 1-1e-3] and to
2.5e-4 over [1e-6, 1-1e-6]; the residual is the CDF's own error divided by a vanishing
density, and it is invisible at the scale of a rank correlation.
``tests/model/test_gaussian.py`` pins all of this against ``math.erf`` and SciPy.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

__all__ = ["norm_cdf", "norm_ppf"]

Floats = NDArray[np.float64]

# Abramowitz & Stegun 7.1.26.
_A1 = 0.254829592
_A2 = -0.284496736
_A3 = 1.421413741
_A4 = -1.453152027
_A5 = 1.061405429
_P = 0.3275911

# Acklam's inverse-normal coefficients.
_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_ACKLAM_SPLIT_LOW = 0.02425
_INV_SQRT_2PI = 0.3989422804014327


def _erf(x: Floats) -> Floats:
    """Abramowitz & Stegun 7.1.26, extended to negative arguments by odd symmetry."""
    sign = np.sign(x)
    absolute = np.abs(x)
    t = 1.0 / (1.0 + _P * absolute)
    polynomial = t * (_A1 + t * (_A2 + t * (_A3 + t * (_A4 + t * _A5))))
    return sign * (1.0 - polynomial * np.exp(-absolute * absolute))


def norm_cdf(z: NDArray[np.float64] | float) -> Floats:
    """Standard normal cumulative distribution function."""
    array = np.asarray(z, dtype=np.float64)
    return 0.5 * (1.0 + _erf(array / np.sqrt(2.0)))


def norm_ppf(p: NDArray[np.float64] | float) -> Floats:
    """Standard normal quantile function.

    Values at or outside ``(0, 1)`` are clipped into the open interval rather than returning
    infinities: every caller here feeds it an empirical probability-integral transform, and
    an exact 0 or 1 there means "at or beyond the observed range", not "impossible".
    """
    array = np.asarray(p, dtype=np.float64)
    clipped = np.clip(array, 1e-12, 1.0 - 1e-12)
    result = np.empty_like(clipped)

    lower = clipped < _ACKLAM_SPLIT_LOW
    upper = clipped > 1.0 - _ACKLAM_SPLIT_LOW
    central = ~(lower | upper)

    if np.any(central):
        q = clipped[central] - 0.5
        r = q * q
        numerator = (
            (
                (((_ACKLAM_A[0] * r + _ACKLAM_A[1]) * r + _ACKLAM_A[2]) * r + _ACKLAM_A[3]) * r
                + _ACKLAM_A[4]
            )
            * r
            + _ACKLAM_A[5]
        ) * q
        denominator = (
            (((_ACKLAM_B[0] * r + _ACKLAM_B[1]) * r + _ACKLAM_B[2]) * r + _ACKLAM_B[3]) * r
            + _ACKLAM_B[4]
        ) * r + 1.0
        result[central] = numerator / denominator

    for mask, transform, flip in ((lower, clipped, 1.0), (upper, 1.0 - clipped, -1.0)):
        if not np.any(mask):
            continue
        q = np.sqrt(-2.0 * np.log(transform[mask] if flip > 0 else (1.0 - clipped)[mask]))
        numerator = (
            (((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q + _ACKLAM_C[3]) * q
            + _ACKLAM_C[4]
        ) * q + _ACKLAM_C[5]
        denominator = (
            ((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q + _ACKLAM_D[3]
        ) * q + 1.0
        result[mask] = flip * numerator / denominator

    # One Halley step against the CDF above. Acklam's approximation is accurate to ~1.15e-9
    # relative on its own; the refinement removes the residual and makes the two functions
    # mutually consistent, which is what the copula round trip actually needs.
    error = norm_cdf(result) - clipped
    density = _INV_SQRT_2PI * np.exp(-0.5 * result * result)
    safe = density > 1e-300
    step = np.zeros_like(result)
    step[safe] = error[safe] / density[safe]
    result = result - step / (1.0 + result * step / 2.0)
    return result
