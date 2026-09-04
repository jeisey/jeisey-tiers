"""Offline per-player feature attribution, separated by model component.

`docs/RELEASE2_ROADMAP.md` 11.6 names the gap this closes:

> Release 1 currently cannot answer "exactly why Player A ranked above Player B" from
> published artifacts.

The answer here is an **engineering** answer, not a product one. Nothing in this module is
published to the frontend; it exists so that an engineer looking at a ranking that seems
wrong can see which features moved the availability component and which moved the
performance component, instead of guessing from raw feature values.

**Exact TreeSHAP, not an approximation.** LightGBM computes exact Shapley values for tree
ensembles through ``predict(..., pred_contrib=True)``, so no extra dependency is needed and
there is no sampling to be non-deterministic about. The contributions of one row sum, with
the base value, to exactly the booster's own prediction - which is asserted by a test rather
than assumed, because a summation identity that silently stops holding is how an attribution
becomes decorative.

**The median ladder is what gets explained.** Each component is five boosters, one per
quantile. The P50 booster is the one whose output a reader means by "the model's estimate",
so it is the one attributed; the other four are available through ``level=`` for anyone
chasing a tail problem specifically.

The two components answer different questions and are never merged:

``availability``
    why the model expects this player to be active for that share of the remaining weeks.
``performance``
    why it expects that many points in the games he does play.

A ranking pathology is nearly always one or the other, and pooling them would hide which.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.ros.candidates import RC1_VERSION, FittedComponents
from ffdraft.ros.estimators import ROS_TARGET_COLUMN

__all__ = [
    "ATTRIBUTION_VERSION",
    "DEFAULT_TOP_K",
    "Contribution",
    "PlayerAttribution",
    "attribute_component",
    "attribute_players",
]

Floats = NDArray[np.float64]

#: Bump when the attribution's meaning changes.
ATTRIBUTION_VERSION = "ros_attribution_v1"

#: How many contributors each direction reports. Five is enough to see the story and short
#: enough to read; the full vector is always available from :func:`attribute_component`.
DEFAULT_TOP_K = 5

#: The quantile explained by default. See the module docstring.
MEDIAN_LEVEL = 0.50

_COMPONENTS: tuple[str, ...] = ("availability", "performance")


@dataclass(frozen=True, slots=True)
class Contribution:
    """One feature's signed contribution to one player's component estimate."""

    feature: str
    value: float | None
    contribution: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "value": self.value,
            "contribution": round(self.contribution, 6),
        }


@dataclass(frozen=True, slots=True)
class PlayerAttribution:
    """Both components' attributions for one snapshot row."""

    season: int
    through_week: int
    player_id: str
    display_name: str | None
    position: str
    scoring_preset: str
    level: float
    components: dict[str, dict[str, Any]]
    actual_remaining_points: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribution_version": ATTRIBUTION_VERSION,
            "model_version": RC1_VERSION,
            "season": self.season,
            "through_week": self.through_week,
            "player_id": self.player_id,
            "display_name": self.display_name,
            "position": self.position,
            "scoring_preset": self.scoring_preset,
            "explained_level": self.level,
            "actual_remaining_points": self.actual_remaining_points,
            **{
                f"{component}_{direction}_contributors": [
                    item.to_dict() for item in payload[direction]
                ]
                for component, payload in self.components.items()
                for direction in ("top_positive", "top_negative")
            },
            "component_estimates": {
                component: {
                    "base_value": round(payload["base_value"], 6),
                    "estimate": round(payload["estimate"], 6),
                    "contribution_sum": round(payload["contribution_sum"], 6),
                }
                for component, payload in self.components.items()
            },
        }


def _booster_for(
    boosters: Sequence[lgb.Booster], levels: Sequence[float], level: float
) -> lgb.Booster:
    try:
        index = list(levels).index(level)
    except ValueError as error:  # pragma: no cover - a caller asking for an unfitted level
        raise KeyError(
            f"level {level} is not one of the fitted quantiles {list(levels)}",
        ) from error
    return boosters[index]


def attribute_component(
    boosters: Sequence[lgb.Booster],
    levels: Sequence[float],
    matrix: Floats,
    *,
    level: float = MEDIAN_LEVEL,
) -> tuple[Floats, Floats]:
    """Exact SHAP contributions and base values for one component.

    Returns ``(contributions, base_values)`` where ``contributions`` is
    ``(n_rows, n_features)`` and ``base_values`` is ``(n_rows,)``. Their row sums add to the
    booster's own prediction exactly, which is what makes an attribution checkable.
    """
    booster = _booster_for(boosters, levels, level)
    raw = np.asarray(booster.predict(matrix, pred_contrib=True), dtype=np.float64)
    return raw[:, :-1], raw[:, -1]


def _top(
    features: Sequence[str],
    values: Floats,
    contributions: Floats,
    *,
    top_k: int,
) -> dict[str, Any]:
    order = np.argsort(contributions, kind="stable")
    negative = [
        Contribution(
            feature=features[int(index)],
            value=None if not np.isfinite(values[int(index)]) else float(values[int(index)]),
            contribution=float(contributions[int(index)]),
        )
        for index in order[:top_k]
        if contributions[int(index)] < 0.0
    ]
    positive = [
        Contribution(
            feature=features[int(index)],
            value=None if not np.isfinite(values[int(index)]) else float(values[int(index)]),
            contribution=float(contributions[int(index)]),
        )
        for index in order[::-1][:top_k]
        if contributions[int(index)] > 0.0
    ]
    return {"top_positive": positive, "top_negative": negative}


def attribute_players(
    fitted: FittedComponents,
    rows: pl.DataFrame,
    *,
    level: float = MEDIAN_LEVEL,
    top_k: int = DEFAULT_TOP_K,
) -> list[PlayerAttribution]:
    """Attribute both components for every row of ``rows``.

    ``rows`` must be snapshot rows in the same shape the model was fitted on. They are
    usually a handful of players an engineer is looking at, not a whole board: the point is
    observability, and a full-board attribution is a 400,000-row artifact nobody reads.
    """
    if rows.is_empty():
        return []
    matrix = fitted.design(rows)
    per_component: dict[str, tuple[Floats, Floats]] = {
        "availability": attribute_component(
            fitted.availability,
            fitted.levels,
            matrix,
            level=level,
        ),
        "performance": attribute_component(
            fitted.performance,
            fitted.levels,
            matrix,
            level=level,
        ),
    }
    names = list(fitted.features)
    keys = rows.select(
        "season",
        "through_week",
        "player_id",
        "position",
        "scoring_preset",
        *(
            [pl.col("display_name")]
            if "display_name" in rows.columns
            else [pl.lit(None, dtype=pl.String).alias("display_name")]
        ),
        *(
            [pl.col(ROS_TARGET_COLUMN)]
            if ROS_TARGET_COLUMN in rows.columns
            else [pl.lit(None, dtype=pl.Float64).alias(ROS_TARGET_COLUMN)]
        ),
    ).to_dicts()

    output: list[PlayerAttribution] = []
    for index, key in enumerate(keys):
        components: dict[str, dict[str, Any]] = {}
        for component in _COMPONENTS:
            contributions, base = per_component[component]
            row = contributions[index]
            payload: dict[str, Any] = dict(_top(names, matrix[index], row, top_k=top_k))
            payload["base_value"] = float(base[index])
            payload["contribution_sum"] = float(np.sum(row))
            payload["estimate"] = float(base[index] + np.sum(row))
            components[component] = payload
        actual = key.get(ROS_TARGET_COLUMN)
        output.append(
            PlayerAttribution(
                season=int(key["season"]),
                through_week=int(key["through_week"]),
                player_id=str(key["player_id"]),
                display_name=key.get("display_name"),
                position=str(key["position"]),
                scoring_preset=str(key["scoring_preset"]),
                level=level,
                components=components,
                actual_remaining_points=None if actual is None else float(actual),
            ),
        )
    return output
