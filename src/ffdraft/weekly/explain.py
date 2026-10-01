"""Why this week is different from his typical week (``typical_week_shapley_v1``).

A manager does not need to be told that a good receiver projects well; he knows. He needs to
know why **this** week is better or worse than the receiver's usual week, at the median and at
the ceiling. So the explanation is a *difference*:

    published quantile this week  -  the same quantile in his typical week

and it is split, exactly, into the game-specific factors that make up the difference.

**His typical week** is a deterministic, pregame-only reference. Everything about *him* — form,
role, availability, his offence, his track record — is held at its value this week, so none of
it can appear in the difference; only the game changes. The game is replaced by a weighted set
of ordinary games for him (:func:`reference_backgrounds`):

* **lines** — his team's mean posted total, spread and implied points over its completed games
  this season, shrunk toward the league's mean by :data:`REFERENCE_SHRINK_GAMES` games, so a
  team with one game (the fallback for limited history) reads mostly as an average team;
* **home** — half at home, half away;
* **roof** — indoors in the share of games his team has played indoors, shrunk the same way;
* **rest** — equal rest;
* **opponent** — a league-average defence at the same cutoff: allowed points equal to the
  league's rate for his position and preset, index 1.0, the league's mean prior-season rate and
  mean games played;
* any v2 family — unknown (``null``), the input state the model learned for "not known",
  which is its average over the states it saw.

**Exact, not approximate.** For each explained level the booster is evaluated at every
coalition of factor groups (each group either at this week's value or at the reference value),
for every reference game, and the Shapley value of each group is computed exactly over those
coalitions and averaged with the reference weights (a weighted baseline Shapley value). The
group values sum, with no remainder, to the booster's raw difference.

**Calibration and rearrangement, accounted.** A published quantile is the raw booster plus its
split-conformal shift, sorted across levels. The shift is the same constant in this week and in
the reference, so its term is exactly 0 and is published as such; the monotone repair can move a
level in either, so the difference it makes is published as ``rearrangement`` (which also
absorbs rounding to the published two decimals), and the account closes:

    typical + sum(terms) + calibration + rearrangement == this_week

A term is a model attribution: it says how much this model's number moved with that input,
holding the others. It is not a measured causal effect, and the page says so.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.preprocessing import design_matrix

__all__ = [
    "EXPLAINED_LEVELS",
    "explain_frame",
    "opponent_reference",
    "published_explanation",
    "EXPLANATION_RULE_VERSION",
    "REFERENCE_SHRINK_GAMES",
    "V1_EXPLANATION_GROUPS",
    "ExplanationGroup",
    "explain_rows",
    "reference_backgrounds",
    "team_line_reference",
]

EXPLANATION_RULE_VERSION = "typical_week_shapley_v1"

#: Floor, median and ceiling: the three readings a start/sit decision turns on.
EXPLAINED_LEVELS: tuple[float, ...] = (0.10, 0.50, 0.90)

#: Games of league-average lines mixed into a team's own, as the opponent reading does.
REFERENCE_SHRINK_GAMES = 3.0

Floats = NDArray[np.float64]


@dataclass(frozen=True)
class ExplanationGroup:
    """A set of game-specific inputs explained together, named the way the page names it."""

    key: str
    features: tuple[str, ...]
    label: str


#: The game-specific inputs of ``weekly-startsit-v1``, grouped as a reader thinks of them.
V1_EXPLANATION_GROUPS: tuple[ExplanationGroup, ...] = (
    ExplanationGroup(
        "lines",
        ("game_total_line", "game_team_margin", "game_team_points"),
        "Sportsbook outlook",
    ),
    ExplanationGroup("home", ("game_is_home",), "Home or away"),
    ExplanationGroup("rest", ("game_rest_advantage",), "Rest"),
    ExplanationGroup("roof", ("game_indoors",), "Roof"),
    ExplanationGroup(
        "opponent",
        ("opp_allowed_ppg", "opp_allowed_index", "opp_allowed_prior_ppg", "opp_games_to_date"),
        "Opponent",
    ),
)


def _shrunk(own_sum: float, own_n: int, league_mean: float, k: float) -> float:
    return (own_sum + k * league_mean) / (own_n + k)


def team_line_reference(
    context: pl.DataFrame,
    *,
    season: int,
    through_week: int,
    shrink_games: float = REFERENCE_SHRINK_GAMES,
) -> dict[str, dict[str, float]]:
    """Per team: its typical lines and indoor share from completed games, shrunk to the league.

    ``context`` is :func:`ffdraft.weekly.context.team_game_context` for the season (one row per
    team-game, both sides). Only games in weeks ``<= through_week`` are read: the posted lines
    of games already played, which were public before each of them kicked off.
    """
    played = context.filter(
        (pl.col("season") == season)
        & (pl.col("week") <= through_week)
        & pl.col("game_total_line").is_not_null()
        & pl.col("game_team_margin").is_not_null(),
    )
    if played.is_empty():
        return {}
    league_total = float(played.get_column("game_total_line").mean())  # type: ignore[arg-type]
    indoor_known = played.filter(pl.col("game_indoors").is_not_null())
    league_indoor = (
        float(indoor_known.get_column("game_indoors").mean())  # type: ignore[arg-type]
        if not indoor_known.is_empty()
        else 0.0
    )
    reference: dict[str, dict[str, float]] = {}
    for team, block in played.partition_by("team", as_dict=True).items():
        n = block.height
        total = _shrunk(
            float(block.get_column("game_total_line").sum()), n, league_total, shrink_games
        )
        margin = _shrunk(float(block.get_column("game_team_margin").sum()), n, 0.0, shrink_games)
        indoor = block.filter(pl.col("game_indoors").is_not_null())
        indoor_share = _shrunk(
            float(indoor.get_column("game_indoors").sum()),
            indoor.height,
            league_indoor,
            shrink_games,
        )
        reference[str(team[0])] = {
            "games": float(n),
            "total": total,
            "margin": margin,
            "team_points": (total + margin) / 2.0,
            "indoors_share": min(1.0, max(0.0, indoor_share)),
        }
    reference["__league__"] = {
        "games": 0.0,
        "total": league_total,
        "margin": 0.0,
        "team_points": league_total / 2.0,
        "indoors_share": min(1.0, max(0.0, league_indoor)),
    }
    return reference


def reference_backgrounds(
    row: Mapping[str, Any],
    *,
    lines: Mapping[str, Mapping[str, float]],
    opponent_typical: Mapping[tuple[str, str], Mapping[str, float]],
    team_column: str,
    extra_null_features: Sequence[str] = (),
) -> list[tuple[float, dict[str, float | None]]]:
    """The weighted reference games for one row: ``[(weight, {feature: value}), ...]``.

    Four points at most (home or away x indoors or not), weights summing to one. Only the
    game-specific features appear; everything else stays at the row's own value.
    """
    team = str(row.get(team_column) or "")
    typical = lines.get(team) or lines.get("__league__") or {}
    opponent = opponent_typical.get((str(row["position"]), str(row["scoring_preset"]))) or {}
    shared: dict[str, float | None] = {
        "game_total_line": typical.get("total"),
        "game_team_margin": typical.get("margin"),
        "game_team_points": typical.get("team_points"),
        "game_rest_advantage": 0.0,
        "opp_allowed_ppg": opponent.get("opp_allowed_ppg"),
        "opp_allowed_index": opponent.get("opp_allowed_index"),
        "opp_allowed_prior_ppg": opponent.get("opp_allowed_prior_ppg"),
        "opp_games_to_date": opponent.get("opp_games_to_date"),
        **dict.fromkeys(extra_null_features),
    }
    indoors = float(typical.get("indoors_share", 0.0))
    points: list[tuple[float, dict[str, float | None]]] = []
    for home, home_weight in ((1.0, 0.5), (0.0, 0.5)):
        for indoor, indoor_weight in ((1.0, indoors), (0.0, 1.0 - indoors)):
            weight = home_weight * indoor_weight
            if weight <= 0.0:
                continue
            points.append(
                (weight, {**shared, "game_is_home": home, "game_indoors": indoor}),
            )
    return points


def opponent_reference(allowed: pl.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    """A league-average defence per position and preset, at the cutoff ``allowed`` is for."""
    reference: dict[tuple[str, str], dict[str, float]] = {}
    if allowed.is_empty():
        return reference
    for (position, preset), block in allowed.partition_by(
        "position", "scoring_preset", as_dict=True
    ).items():
        prior = block.get_column("opp_allowed_prior_ppg").drop_nulls()
        reference[(str(position), str(preset))] = {
            "opp_allowed_ppg": float(block.get_column("league_ppg").max()),  # type: ignore[arg-type]
            "opp_allowed_index": 1.0,
            "opp_allowed_prior_ppg": float(prior.mean()) if prior.len() else math.nan,  # type: ignore[arg-type]
            "opp_games_to_date": float(block.get_column("opp_games_to_date").mean()),  # type: ignore[arg-type]
        }
    return reference


def _shapley_weights(groups: int) -> list[float]:
    """``|S|! (G - |S| - 1)! / G!`` for coalition size ``|S|``."""
    return [
        math.factorial(size) * math.factorial(groups - size - 1) / math.factorial(groups)
        for size in range(groups)
    ]


def explain_rows(
    frame: pl.DataFrame,
    *,
    features: Sequence[str],
    boosters: Sequence[Any],
    offsets: Sequence[float],
    levels: Sequence[float],
    explained: Sequence[float],
    groups: Sequence[ExplanationGroup],
    backgrounds: Sequence[Sequence[tuple[float, Mapping[str, float | None]]]],
) -> list[dict[str, Any]]:
    """The explanation of ``explained`` levels for every row of one model group.

    ``boosters``/``offsets`` are the group's seven per level; ``backgrounds[i]`` is row ``i``'s
    reference set. Returns, per row, ``{level_key: {typical, this_week, terms, calibration,
    rearrangement}}`` in unrounded points.
    """
    n = frame.height
    if n == 0:
        return []
    feature_index = {name: index for index, name in enumerate(features)}
    group_columns = [[feature_index[name] for name in group.features] for group in groups]
    count = len(groups)
    masks = 1 << count
    weights = _shapley_weights(count)
    base = design_matrix(frame, features)

    # Every (row, background, coalition) input as one matrix: row-major blocks.
    depth = max(len(points) for points in backgrounds)
    stacked = np.repeat(base, depth * masks, axis=0)
    bg_weight = np.zeros((n, depth), dtype=np.float64)
    for row, points in enumerate(backgrounds):
        for slot in range(depth):
            if slot >= len(points):
                continue
            weight, reference = points[slot]
            bg_weight[row, slot] = weight
            for mask in range(masks):
                target = (row * depth + slot) * masks + mask
                for group_number, columns in enumerate(group_columns):
                    if mask >> group_number & 1:
                        continue
                    for column in columns:
                        value = reference.get(features[column])
                        stacked[target, column] = math.nan if value is None else float(value)
    level_index = {level: index for index, level in enumerate(levels)}
    full_mask = masks - 1

    raw_all = np.column_stack(
        [np.asarray(booster.predict(stacked), dtype=np.float64) for booster in boosters],
    ).reshape(n, depth, masks, len(levels))
    offsets_array = np.asarray(offsets, dtype=np.float64)

    def published(raw: Floats) -> Floats:
        return np.sort(np.sort(raw, axis=-1) + offsets_array, axis=-1)

    this_raw = raw_all[:, 0, full_mask, :]
    this_published = published(this_raw)
    reference_raw = raw_all[:, :, 0, :]
    reference_published = published(reference_raw)
    output: list[dict[str, Any]] = [{} for _ in range(n)]
    for level in explained:
        li = level_index[level]
        level_raw = raw_all[:, :, :, li]
        terms = np.zeros((n, count), dtype=np.float64)
        for group_number in range(count):
            bit = 1 << group_number
            for mask in range(masks):
                if mask & bit:
                    continue
                size = bin(mask).count("1")
                delta = level_raw[:, :, mask | bit] - level_raw[:, :, mask]
                terms[:, group_number] += weights[size] * np.sum(delta * bg_weight, axis=1)
        typical = np.sum(reference_published[:, :, li] * bg_weight, axis=1)
        typical_raw = np.sum((reference_raw[:, :, li] + offsets_array[li]) * bg_weight, axis=1)
        this_week = this_published[:, li]
        this_raw_calibrated = this_raw[:, li] + offsets_array[li]
        rearrangement = (this_week - this_raw_calibrated) - (typical - typical_raw)
        for row in range(n):
            output[row][f"q{round(level * 100):02d}"] = {
                "typical": float(typical[row]),
                "this_week": float(this_week[row]),
                "terms": {
                    group.key: float(terms[row, group_number])
                    for group_number, group in enumerate(groups)
                },
                "calibration": 0.0,
                "rearrangement": float(rearrangement[row]),
            }
    return output


def rounded_account(level: Mapping[str, Any], published: float) -> dict[str, Any]:
    """Two decimals, closed: ``rearrangement`` absorbs rounding, so the parts sum exactly."""
    terms = {key: round(float(value), 2) for key, value in level["terms"].items()}
    typical = round(float(level["typical"]), 2)
    calibration = 0.0
    rearrangement = round(published - typical - sum(terms.values()) - calibration, 2)
    return {
        "typical": typical,
        "terms": terms,
        "calibration": calibration,
        "rearrangement": rearrangement,
    }


def explain_frame(
    model: Any,
    frame: pl.DataFrame,
    *,
    lines: Mapping[str, Mapping[str, float]],
    opponent_typical: Mapping[tuple[str, str], Mapping[str, float]],
    team_column: str,
    groups: Sequence[ExplanationGroup] = V1_EXPLANATION_GROUPS,
    explained: Sequence[float] = EXPLAINED_LEVELS,
    extra_null_features: Sequence[str] = (),
) -> list[dict[str, Any] | None]:
    """Explanations for every row of ``frame`` under ``model``, row order preserved.

    A row whose position and preset the model has no group for gets ``None``.
    """
    output: list[dict[str, Any] | None] = [None] * frame.height
    if frame.is_empty():
        return output
    indexed = frame.with_row_index("_explain_row")
    for group in model.groups.values():
        block = indexed.filter(
            (pl.col("position") == group.position)
            & (pl.col("scoring_preset") == group.scoring_preset),
        )
        if block.is_empty():
            continue
        backgrounds = [
            reference_backgrounds(
                row,
                lines=lines,
                opponent_typical=opponent_typical,
                team_column=team_column,
                extra_null_features=extra_null_features,
            )
            for row in block.iter_rows(named=True)
        ]
        accounts = explain_rows(
            block,
            features=model.spec.features,
            boosters=group.boosters,
            offsets=group.offsets,
            levels=model.levels,
            explained=explained,
            groups=groups,
            backgrounds=backgrounds,
        )
        for row, account in zip(block.get_column("_explain_row").to_list(), accounts, strict=True):
            output[int(row)] = account
    return output


def published_explanation(
    account: Mapping[str, Any] | None,
    quantiles: Mapping[str, float],
) -> dict[str, Any] | None:
    """The record's ``explanation`` block: each explained level's closed, rounded account."""
    if account is None:
        return None
    return {key: rounded_account(level, float(quantiles[key])) for key, level in account.items()}
