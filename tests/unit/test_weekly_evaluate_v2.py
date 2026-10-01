"""The frozen v2 development procedure runs end to end and decides by its declared rule."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.weekly.evaluate_v2 import (
    V2Fold,
    bootstrap_pinball_difference,
    family_selection,
    run_v2_development,
)
from ffdraft.weekly.frozen_v2 import CANDIDATE_VARIANTS, V2_FAMILIES

Rows = Callable[..., pl.DataFrame]


def _fast(spec: Any) -> Any:
    return replace(spec, num_boost_round=6)


def _with_v2_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Every v2 input, a third of each family missing, as serving can leave it."""
    rng = np.random.default_rng(7)
    height = frame.height
    columns: dict[str, Any] = {}
    for family, names in V2_FAMILIES.items():
        missing = rng.uniform(size=height) < 1 / 3
        for name in names:
            values = (
                rng.uniform(0, 30, height) if name.startswith("wx_") else rng.integers(0, 3, height)
            )
            columns[name] = [
                None if gone else float(value) for gone, value in zip(missing, values, strict=True)
            ]
        del family
    return frame.with_columns(
        [pl.Series(name, values, dtype=pl.Float64) for name, values in columns.items()]
    )


def test_the_development_run_scores_every_variant_and_decides_once(weekly_rows: Rows) -> None:
    frame = _with_v2_columns(weekly_rows(range(2017, 2026), per_season=60))
    result = run_v2_development(frame, weather_parameters_digest="test", _spec_transform=_fast)
    assert result["folds"] == [2020, 2021, 2022, 2023, 2024]
    assert set(CANDIDATE_VARIANTS) <= set(result["pooled"])
    assert set(result["selection"]["families"]) == set(V2_FAMILIES)
    for family, verdict in result["selection"]["families"].items():
        assert set(verdict["clauses"]) == {
            "pinball_below_v1",
            "pinball_interval_above_zero",
            "pinball_fold_wins",
            "decision_not_worse",
        }, family
    assert result["outcome"] in {"selected", "rejected_at_development"}
    # 2025 is re-examined only when there is a v2 to re-examine, and never decides.
    assert (result["previously_examined"] is None) == (result["v2_variant"] is None)
    # Seasons after 2024 never reach a development fold.
    assert 2025 not in result["_rows"].get_column("season").to_list()


def test_the_development_run_is_deterministic(weekly_rows: Rows) -> None:
    frame = _with_v2_columns(weekly_rows(range(2017, 2022), per_season=40))
    first = run_v2_development(
        frame,
        weather_parameters_digest="test",
        seasons=(2020, 2021),
        include_previously_examined=False,
        _spec_transform=_fast,
    )
    second = run_v2_development(
        frame,
        weather_parameters_digest="test",
        seasons=(2020, 2021),
        include_previously_examined=False,
        _spec_transform=_fast,
    )
    # NaN (a metric with no pairs in this tiny frame) is equal to itself only as text.
    assert json.dumps(first["pooled"], sort_keys=True) == json.dumps(
        second["pooled"], sort_keys=True
    )
    assert first["_rows"].equals(second["_rows"])


def _fold_rows(season: int, v1: float, others: dict[str, float]) -> pl.DataFrame:
    weeks = list(range(1, 11))
    data: dict[str, Any] = {
        "season": [season] * 10,
        "target_week": weeks,
        "position": ["WR"] * 10,
        "scoring_preset": ["PPR"] * 10,
        "v1__pinball": [v1 + 0.01 * (week % 3) for week in weeks],
    }
    for name, value in others.items():
        data[f"{name}__pinball"] = [value + 0.01 * (week % 3) for week in weeks]
    return pl.DataFrame(data)


def _pooled(accuracy: float = 0.66, brier: float = 0.21) -> dict[str, float]:
    return {"pinball": 0.0, "pair_accuracy": accuracy, "pair_brier": brier}


def test_a_family_that_beats_v1_everywhere_is_selected_and_a_tie_is_not() -> None:
    others = {"v1+weather": 0.9, "v1+lineup": 1.0, "v1+defense": 1.05}
    folds = [
        V2Fold(season=season, rows=_fold_rows(season, 1.0, others), pairs={})
        for season in range(2020, 2025)
    ]
    rows = pl.concat([fold.rows for fold in folds])
    pooled = {
        "v1": {**_pooled(), "pinball": 1.01},
        "v1+weather": {**_pooled(), "pinball": 0.91},
        "v1+lineup": {**_pooled(), "pinball": 1.01},
        "v1+defense": {**_pooled(), "pinball": 1.06},
    }
    result = family_selection(rows, folds, pooled)
    assert result["selected"] == ["weather"]
    lineup = result["families"]["lineup"]["clauses"]
    assert not lineup["pinball_below_v1"]["passed"]
    assert not lineup["pinball_interval_above_zero"]["passed"]


def test_a_family_that_costs_the_decision_is_not_selected() -> None:
    others = {"v1+weather": 0.9, "v1+lineup": 1.1, "v1+defense": 1.1}
    folds = [
        V2Fold(season=season, rows=_fold_rows(season, 1.0, others), pairs={})
        for season in range(2020, 2025)
    ]
    rows = pl.concat([fold.rows for fold in folds])
    pooled = {
        "v1": {**_pooled(), "pinball": 1.01},
        "v1+weather": {**_pooled(accuracy=0.65), "pinball": 0.91},
        "v1+lineup": {**_pooled(), "pinball": 1.11},
        "v1+defense": {**_pooled(), "pinball": 1.11},
    }
    result = family_selection(rows, folds, pooled)
    assert result["selected"] == []
    assert not result["families"]["weather"]["clauses"]["decision_not_worse"]["passed"]


def test_the_pinball_interval_is_week_clustered_and_signed_for_the_candidate() -> None:
    rows = _fold_rows(2020, 1.0, {"v1+weather": 0.8})
    interval = bootstrap_pinball_difference(rows, "v1", "v1+weather", replicates=200, level=0.95)
    assert interval["clusters"] == 10
    assert interval["difference"] == pytest.approx(0.2)
    assert interval["lower"] > 0.0
