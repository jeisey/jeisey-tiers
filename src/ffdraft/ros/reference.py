"""The climatological reference: what calibration can actually attain on a cohort.

A P10-P90 interval is conventionally expected to cover 80% of outcomes. That expectation is a
theorem about **continuous** targets, and the rest-of-season target is not continuous: 56.8% of
development rows have an outcome of exactly zero, and 88.5% of the zero-current-games cohort
does.

The arithmetic is unavoidable. Write ``F`` for a row's true predictive CDF and
``F^-1(u) = inf{y : F(y) >= u}`` for the generalized inverse a quantile model reports. A
**perfectly calibrated** forecaster's closed interval covers

    P(F^-1(0.10) <= Y <= F^-1(0.90)) = F(F^-1(0.90)) - F(F^-1(0.10)-)

For continuous ``F`` both terms are exact and the coverage is 0.80. But if ``F`` has an atom of
mass ``p >= 0.10`` at zero and the outcome is bounded below by it, then ``F^-1(0.10) = 0``,
``F(0-) = 0``, and the coverage is ``F(F^-1(0.90)) >= 0.90``. If ``p >= 0.90`` the interval
collapses to the single point zero and the coverage is ``p`` itself.

So on a zero-inflated cohort a *perfect* forecaster is pushed **above** 0.90, and can be pushed
above 0.95. An absolute upper bound on coverage therefore does not measure what it was written
to measure: it measures how much probability mass the target puts on a single point.

This module supplies the reference such a bound has to be stated against. For one cohort it
computes what a forecaster that knows the evaluation cell and the cohort, but nothing about the
individual player, would attain:

* within each evaluation cell, the empirical P10 and P90 of that cohort's **actual** outcomes;
* falling back to the cohort's pooled empirical quantiles when a cell holds too few rows;
* row-weighted means of the resulting coverage and width.

Three properties make it usable as a gate reference rather than as a model.

**It is calibrated by construction.** It is the empirical distribution of the very rows being
judged, so its coverage is the coverage calibration attains there, up to sampling noise.

**It is computed from outcomes only.** No model input, no prediction, no fitted parameter. It
is a diagnostic of the *target distribution*, identical for every model compared against it,
and it can never win or lose a comparison.

**It is the honest definition of "an interval so wide it says nothing".** An interval wider
than climatology is wider than knowing nothing at all, which is what uselessness means. An atom
at zero makes a calibrated interval *narrower*, so a width bound stated against climatology
cannot be tripped by the atom the coverage bound was tripped by.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

__all__ = [
    "CLIMATOLOGY_VERSION",
    "MINIMUM_CELL_ROWS",
    "REFERENCE_LEVELS",
    "CohortReference",
    "cohort_reference",
]

#: Bump when the reference's construction changes.
CLIMATOLOGY_VERSION = "ros_climatology_v1"

#: The interval the reference describes, matching the gate's own P10-P90 clause.
REFERENCE_LEVELS: tuple[float, float] = (0.10, 0.90)

#: A cell with fewer cohort rows than this cannot estimate its own deciles; those rows fall
#: back to the cohort's pooled quantiles. Twenty is the smallest sample at which an empirical
#: decile is a decile rather than an order statistic standing in for one.
MINIMUM_CELL_ROWS = 20

_CELL_KEYS: tuple[str, ...] = ("season", "through_week", "position", "scoring_preset")


@dataclass(frozen=True, slots=True)
class CohortReference:
    """What a calibrated, player-blind forecaster attains on one cohort."""

    rows: int
    coverage: float
    width: float
    zero_share: float
    cells: int
    pooled_rows: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "climatology_version": CLIMATOLOGY_VERSION,
            "rows": self.rows,
            "coverage": self.coverage,
            "width": self.width,
            "zero_share": self.zero_share,
            "cells": self.cells,
            "rows_using_pooled_quantiles": self.pooled_rows,
        }


def cohort_reference(
    frame: pl.DataFrame,
    *,
    target_column: str,
    cell_keys: Sequence[str] = _CELL_KEYS,
    minimum_cell_rows: int = MINIMUM_CELL_ROWS,
) -> CohortReference:
    """Compute the climatological reference for the rows of ``frame``.

    ``frame`` is one cohort's rows, already masked. Every quantity returned is a function of
    ``target_column`` alone.
    """
    if frame.is_empty():
        return CohortReference(0, float("nan"), float("nan"), float("nan"), 0, 0)

    outcomes = frame.get_column(target_column).to_numpy().astype(np.float64)
    pooled_low, pooled_high = (
        float(value) for value in np.quantile(outcomes, list(REFERENCE_LEVELS))
    )

    covered = 0.0
    width = 0.0
    pooled_rows = 0
    cells = 0
    for _, cell in frame.group_by(list(cell_keys), maintain_order=True):
        values = cell.get_column(target_column).to_numpy().astype(np.float64)
        cells += 1
        if values.size >= minimum_cell_rows:
            low, high = (float(value) for value in np.quantile(values, list(REFERENCE_LEVELS)))
        else:
            low, high = pooled_low, pooled_high
            pooled_rows += int(values.size)
        covered += float(np.count_nonzero((values >= low) & (values <= high)))
        width += float(high - low) * values.size

    total = float(outcomes.size)
    return CohortReference(
        rows=int(outcomes.size),
        coverage=covered / total,
        width=width / total,
        zero_share=float(np.count_nonzero(outcomes == 0.0)) / total,
        cells=cells,
        pooled_rows=pooled_rows,
    )
