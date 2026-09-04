"""Offline per-player attribution.

The summation identity is the whole reason to trust an attribution: exact TreeSHAP
contributions plus the base value equal the booster's own prediction. A test that only
checked "some features came back" would keep passing after the attribution stopped
describing the model.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.ros.attribution import (
    ATTRIBUTION_VERSION,
    DEFAULT_TOP_K,
    attribute_component,
    attribute_players,
)
from ffdraft.ros.candidates import RC1_VERSION, RosHurdleCandidate


@pytest.fixture(scope="module")
def fitted(ros_dataset, ros_fit_context):
    group = (pl.col("position") == ros_fit_context.position) & (
        pl.col("scoring_preset") == ros_fit_context.scoring_preset
    )
    train = ros_dataset.frame.filter(
        pl.col("season").is_in(list(ros_fit_context.fold.train_seasons)) & group,
    )
    candidate = RosHurdleCandidate(num_boost_round=40, composition_draws=200)
    return candidate.fit_components(train, ros_fit_context)


@pytest.fixture(scope="module")
def rows(ros_dataset, ros_fit_context):
    group = (pl.col("position") == ros_fit_context.position) & (
        pl.col("scoring_preset") == ros_fit_context.scoring_preset
    )
    return ros_dataset.frame.filter(
        (pl.col("season") == ros_fit_context.fold.validation_season)
        & group
        & (pl.col("through_week") == 8),
    ).head(12)


def test_contributions_and_the_base_value_reproduce_the_booster(fitted, rows) -> None:
    matrix = fitted.design(rows)
    for boosters in (fitted.availability, fitted.performance):
        contributions, base = attribute_component(boosters, fitted.levels, matrix)
        index = list(fitted.levels).index(0.50)
        predicted = boosters[index].predict(matrix)
        assert np.allclose(contributions.sum(axis=1) + base, predicted, atol=1e-9)


def test_attribution_is_deterministic(fitted, rows) -> None:
    left = attribute_players(fitted, rows)
    right = attribute_players(fitted, rows)
    assert [item.to_dict() for item in left] == [item.to_dict() for item in right]


def test_each_row_reports_both_components_in_both_directions(fitted, rows) -> None:
    attributions = attribute_players(fitted, rows)
    assert len(attributions) == rows.height
    for item in attributions:
        payload = item.to_dict()
        assert payload["attribution_version"] == ATTRIBUTION_VERSION
        assert payload["model_version"] == RC1_VERSION
        for component in ("availability", "performance"):
            positive = payload[f"{component}_top_positive_contributors"]
            negative = payload[f"{component}_top_negative_contributors"]
            assert len(positive) <= DEFAULT_TOP_K
            assert len(negative) <= DEFAULT_TOP_K
            assert all(entry["contribution"] > 0 for entry in positive)
            assert all(entry["contribution"] < 0 for entry in negative)
            estimate = payload["component_estimates"][component]
            assert estimate["base_value"] + estimate["contribution_sum"] == pytest.approx(
                estimate["estimate"],
            )


def test_the_contributors_are_ordered_by_magnitude(fitted, rows) -> None:
    for item in attribute_players(fitted, rows):
        for component in ("availability", "performance"):
            positive = [
                entry["contribution"]
                for entry in item.to_dict()[f"{component}_top_positive_contributors"]
            ]
            assert positive == sorted(positive, reverse=True)


def test_every_named_contributor_is_a_declared_model_input(fitted, rows) -> None:
    allowed = set(fitted.features)
    for item in attribute_players(fitted, rows):
        payload = item.to_dict()
        for key, entries in payload.items():
            if key.endswith("_contributors"):
                assert {entry["feature"] for entry in entries} <= allowed


def test_an_unfitted_quantile_level_is_refused(fitted, rows) -> None:
    with pytest.raises(KeyError, match="not one of the fitted quantiles"):
        attribute_component(fitted.availability, fitted.levels, fitted.design(rows), level=0.42)


def test_an_empty_row_set_produces_nothing(fitted, rows) -> None:
    assert attribute_players(fitted, rows.head(0)) == []
