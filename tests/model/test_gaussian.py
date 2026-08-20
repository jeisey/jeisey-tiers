"""The normal CDF and its inverse, pinned twice.

ADR-024 keeps SciPy out of production, so the project owns these two functions. Owning them
means testing them against something independent: ``math.erf`` from the standard library,
and SciPy, which is already installed as a LightGBM dependency and is declared as a
development dependency precisely so cross-checks like this can exist.

The property the copula actually depends on is that the two are mutual inverses, so that is
asserted to a much tighter tolerance than agreement with any outside implementation.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ffdraft.modeling.gaussian import norm_cdf, norm_ppf


def test_cdf_matches_the_standard_library() -> None:
    z = np.linspace(-6.0, 6.0, 2001)
    reference = np.array([0.5 * (1.0 + math.erf(value / math.sqrt(2.0))) for value in z])
    assert float(np.max(np.abs(norm_cdf(z) - reference))) < 1.5e-7


def test_cdf_matches_scipy() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    z = np.linspace(-8.0, 8.0, 4001)
    assert float(np.max(np.abs(norm_cdf(z) - scipy_stats.norm.cdf(z)))) < 1.5e-7


def test_cdf_landmarks() -> None:
    assert norm_cdf(np.array([0.0]))[0] == pytest.approx(0.5, abs=1e-12)
    assert norm_cdf(np.array([1.959963985]))[0] == pytest.approx(0.975, abs=1e-6)
    assert norm_cdf(np.array([-1.959963985]))[0] == pytest.approx(0.025, abs=1e-6)


def test_ppf_is_the_inverse_of_this_cdf() -> None:
    """The property the copula round trip needs, asserted much tighter than outside agreement.

    The residual is A&S 7.1.26's own error near the origin, where the series does not
    evaluate to exactly zero; it is nine orders of magnitude below anything a rank
    correlation can notice.
    """
    p = np.concatenate([np.linspace(1e-6, 1 - 1e-6, 5001), np.array([0.001, 0.5, 0.999])])
    assert float(np.max(np.abs(norm_cdf(norm_ppf(p)) - p))) < 5e-9


def test_ppf_matches_scipy_in_the_useful_range() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    p = np.linspace(1e-3, 1 - 1e-3, 5001)
    assert float(np.max(np.abs(norm_ppf(p) - scipy_stats.norm.ppf(p)))) < 5e-5


def test_ppf_clips_rather_than_returning_infinity() -> None:
    """An empirical PIT can land exactly on 0 or 1; that means 'at the edge', not 'impossible'."""
    values = norm_ppf(np.array([0.0, 1.0]))
    assert np.all(np.isfinite(values))
    assert values[0] < -6.0 < 6.0 < values[1]


def test_ppf_is_odd_around_the_median() -> None:
    p = np.array([0.01, 0.1, 0.25, 0.4])
    assert np.allclose(norm_ppf(p), -norm_ppf(1.0 - p), atol=1e-9)
