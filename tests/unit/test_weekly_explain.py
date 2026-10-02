"""The typical-week explanation: exact Shapley values, a closed account, a pregame reference."""

from __future__ import annotations

import itertools
import math

import lightgbm as lgb
import numpy as np
import polars as pl
import pytest

from ffdraft.weekly.explain import (
    ExplanationGroup,
    explain_rows,
    reference_backgrounds,
    rounded_account,
    team_line_reference,
)

FEATURES = ("form", "a", "b", "c")
GROUPS = (
    ExplanationGroup("ab", ("a", "b"), "A and B"),
    ExplanationGroup("c", ("c",), "C"),
)
LEVELS = (0.1, 0.5, 0.9)


def _boosters() -> list[lgb.Booster]:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(600, 4))
    y = 2 * x[:, 0] + x[:, 1] * x[:, 2] + np.where(x[:, 3] > 0, 1.5, -0.5) + rng.normal(size=600)
    boosters = []
    for level in LEVELS:
        data = lgb.Dataset(x, label=y, feature_name=list(FEATURES), free_raw_data=True)
        boosters.append(
            lgb.train(
                {
                    "objective": "quantile",
                    "alpha": level,
                    "num_leaves": 7,
                    "min_data_in_leaf": 20,
                    "verbosity": -1,
                    "seed": 1,
                    "deterministic": True,
                    "force_row_wise": True,
                },
                data,
                num_boost_round=30,
            ),
        )
    return boosters


def _brute_force(
    booster: lgb.Booster, x: dict[str, float], background: dict[str, float]
) -> dict[str, float]:
    keys = [group.key for group in GROUPS]

    def value(coalition: set[str]) -> float:
        row = {}
        for name in FEATURES:
            owner = next((g.key for g in GROUPS if name in g.features), None)
            row[name] = x[name] if owner is None or owner in coalition else background[name]
        return float(booster.predict(np.array([[row[name] for name in FEATURES]]))[0])

    result: dict[str, float] = {}
    total = len(keys)
    for key in keys:
        others = [k for k in keys if k != key]
        phi = 0.0
        for size in range(len(others) + 1):
            for subset in itertools.combinations(others, size):
                weight = (
                    math.factorial(size) * math.factorial(total - size - 1) / math.factorial(total)
                )
                phi += weight * (value(set(subset) | {key}) - value(set(subset)))
        result[key] = phi
    return result


def test_terms_are_the_exact_weighted_shapley_values_and_the_account_closes() -> None:
    boosters = _boosters()
    offsets = [-0.3, 0.1, 0.4]
    frame = pl.DataFrame({"form": [0.8, -1.2], "a": [1.0, -0.5], "b": [0.5, 2.0], "c": [1.0, -1.0]})
    backgrounds = [
        [(0.25, {"a": 0.0, "b": 0.0, "c": -1.0}), (0.75, {"a": 0.2, "b": -0.1, "c": 1.0})],
        [(1.0, {"a": 0.1, "b": 0.3, "c": 0.0})],
    ]
    out = explain_rows(
        frame,
        features=FEATURES,
        boosters=boosters,
        offsets=offsets,
        levels=LEVELS,
        explained=LEVELS,
        groups=GROUPS,
        backgrounds=backgrounds,
    )
    for row_index, row in enumerate(frame.iter_rows(named=True)):
        for level_index, level in enumerate(LEVELS):
            account = out[row_index][f"q{round(level * 100):02d}"]
            expected = dict.fromkeys(("ab", "c"), 0.0)
            for weight, background in backgrounds[row_index]:
                full = {**row, **background}
                for key, value in _brute_force(boosters[level_index], row, full).items():
                    expected[key] += weight * value
            for key in expected:
                assert account["terms"][key] == pytest.approx(expected[key], abs=1e-9)
            total = (
                account["typical"]
                + sum(account["terms"].values())
                + account["calibration"]
                + account["rearrangement"]
            )
            assert total == pytest.approx(account["this_week"], abs=1e-9)
            # The conformal shift is in both readings, so it cannot explain the difference.
            assert account["calibration"] == 0.0


def test_the_rounded_account_closes_at_two_decimals() -> None:
    level = {"typical": 12.3456, "terms": {"lines": 1.234, "opponent": -0.4449}}
    account = rounded_account(level, 13.14)
    parts = account["typical"] + sum(account["terms"].values()) + account["rearrangement"]
    assert round(parts, 2) == 13.14


def _context(rows: list[tuple[int, str, float, float, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "season": 2025,
                "week": week,
                "team": team,
                "game_total_line": total,
                "game_team_margin": margin,
                "game_indoors": indoors,
            }
            for week, team, total, margin, indoors in rows
        ],
    )


def test_the_typical_lines_read_only_completed_games_and_shrink_to_the_league() -> None:
    context = _context(
        [
            (1, "KC", 50.0, 6.0, 0.0),
            (1, "LV", 50.0, -6.0, 0.0),
            (2, "KC", 52.0, 4.0, 1.0),
            (2, "DEN", 40.0, 0.0, 0.0),
            # A future game cannot shape the typical week.
            (3, "KC", 80.0, 30.0, 1.0),
        ],
    )
    reference = team_line_reference(context, season=2025, through_week=2)
    league = reference["__league__"]
    assert league["total"] == pytest.approx((50 + 50 + 52 + 40) / 4)
    kc = reference["KC"]
    assert kc["total"] == pytest.approx((102 + 3 * league["total"]) / (2 + 3))
    assert kc["margin"] == pytest.approx(10 / 5)
    assert kc["team_points"] == pytest.approx((kc["total"] + kc["margin"]) / 2)
    assert 0.0 <= kc["indoors_share"] <= 1.0


def test_reference_games_are_half_home_and_weighted_by_the_indoor_share() -> None:
    lines = {
        "KC": {"total": 47.0, "margin": 3.0, "team_points": 25.0, "indoors_share": 0.25},
        "__league__": {"total": 45.0, "margin": 0.0, "team_points": 22.5, "indoors_share": 0.3},
    }
    opponent = {
        ("WR", "PPR"): {
            "opp_allowed_ppg": 30.0,
            "opp_allowed_index": 1.0,
            "opp_allowed_prior_ppg": 29.0,
            "opp_games_to_date": 4.0,
        },
    }
    points = reference_backgrounds(
        {"team": "KC", "position": "WR", "scoring_preset": "PPR"},
        lines=lines,
        opponent_typical=opponent,
        team_column="team",
        extra_null_features=("wx_wind_mph",),
    )
    assert sum(weight for weight, _ in points) == pytest.approx(1.0)
    assert {values["game_is_home"] for _, values in points} == {0.0, 1.0}
    indoors = sum(weight for weight, values in points if values["game_indoors"] == 1.0)
    assert indoors == pytest.approx(0.25)
    assert all(values["game_rest_advantage"] == 0.0 for _, values in points)
    assert all(values["opp_allowed_index"] == 1.0 for _, values in points)
    assert all(values["wx_wind_mph"] is None for _, values in points)
