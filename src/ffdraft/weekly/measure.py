"""The numbers the start/sit page publishes beside the model, each measured, none assumed.

A projection answers "what will he score". A start/sit decision needs four more facts, and
each is measured here from **out-of-fold** predictions or from outcomes, so no number on the
page is a constant somebody chose:

``margin``
    How uncertain the *rest* of a fantasy matchup is, which is what turns "who scores more"
    into "who is more likely to win me the week". The variance of a starter's actual points
    around the model's median, by position, summed over a standard lineup (QB, 2 RB, 2 WR,
    TE, 2 FLEX) for both sides. Kickers and defences are not modelled and not counted, so the
    real uncertainty is a little larger than published, and the page says so.
``correlation``
    Whether two players' outcomes move together when they share a game: the Spearman
    correlation of their probability-integral transforms (where each outcome fell inside its
    own predicted distribution), converted to the Gaussian-copula correlation the page uses.
    Measured for teammates by position pair and for opponents.
``startable``
    What a startable week *is* in a given league: the points scored by the last starter at
    each position when every roster fills its lineup from that week's actual scores. League
    size and scoring preset change it, so it is published per preset.
``injuries``
    How often a player carrying each official game designation actually appeared.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl

from ffdraft.config import load_app_config
from ffdraft.weekly.dataset import TARGET_COLUMN
from ffdraft.weekly.evaluate import CANDIDATE_ID
from ffdraft.weekly.frozen import WEEKLY_POSITIONS, WEEKLY_QUANTILE_LEVELS, WEEKLY_SEALED_SEASON
from ffdraft.weekly.injuries import injury_base_rates

__all__ = [
    "LINEUP",
    "STARTER_DEPTH",
    "margin_uncertainty",
    "publishable_measurements",
    "same_game_correlation",
    "startable_thresholds",
]

#: The lineup the margin is summed over: each side's starters. FLEX is taken as one back and
#: one receiver, which is how the flex slots fill in practice.
LINEUP: Mapping[str, float] = {"QB": 1.0, "RB": 3.0, "WR": 3.0, "TE": 1.0}

#: Which rows count as "a starter" when measuring residual spread: per week, the players the
#: model itself ranks inside a twelve-team league's starting pool at that position.
STARTER_DEPTH: Mapping[str, int] = {"QB": 12, "RB": 30, "WR": 30, "TE": 12}

_MEDIAN_INDEX = WEEKLY_QUANTILE_LEVELS.index(0.5)


def _starter_rows(rows: pl.DataFrame) -> pl.DataFrame:
    median = f"{CANDIDATE_ID}__q{_MEDIAN_INDEX}"
    ranked = rows.with_columns(
        pl.col(median)
        .rank(method="ordinal", descending=True)
        .over("season", "target_week", "scoring_preset", "position")
        .alias("_rank"),
    )
    depth = pl.col("position").replace_strict(dict(STARTER_DEPTH), default=0)
    return ranked.filter(pl.col("_rank") <= depth)


def margin_uncertainty(rows: pl.DataFrame) -> dict[str, Any]:
    """Per scoring preset: the per-position residual variance and the lineup total."""
    median = f"{CANDIDATE_ID}__q{_MEDIAN_INDEX}"
    starters = _starter_rows(rows)
    result: dict[str, Any] = {}
    for preset in sorted(starters.get_column("scoring_preset").unique().to_list()):
        block = starters.filter(pl.col("scoring_preset") == preset)
        variance: dict[str, float] = {}
        for position in WEEKLY_POSITIONS:
            part = block.filter(pl.col("position") == position)
            residual = (part.get_column(TARGET_COLUMN) - part.get_column(median)).to_numpy()
            variance[position] = round(float(np.var(residual, ddof=1)), 3)
        side = sum(LINEUP[position] * variance[position] for position in WEEKLY_POSITIONS)
        result[str(preset)] = {
            "position_variance": variance,
            "lineup_variance": round(side, 3),
            # Both sides minus the one slot being decided, for a slot of each position.
            "margin_sd_by_slot": {
                position: round(math.sqrt(2.0 * side - variance[position]), 2)
                for position in WEEKLY_POSITIONS
            },
            "starter_rows": block.height,
        }
    return result


def _pit(rows: pl.DataFrame) -> np.ndarray:
    """Where each outcome fell inside its own predicted distribution, 0-1."""
    from ffdraft.weekly.distribution import knots

    quantiles = rows.select(
        [f"{CANDIDATE_ID}__q{index}" for index in range(len(WEEKLY_QUANTILE_LEVELS))],
    ).to_numpy()
    actual = rows.get_column(TARGET_COLUMN).to_numpy()
    values = np.empty(rows.height, dtype=np.float64)
    for index in range(rows.height):
        taus, points = knots(quantiles[index])
        values[index] = float(np.interp(actual[index], points, taus))
    return values


def same_game_correlation(rows: pl.DataFrame, dataset: pl.DataFrame) -> dict[str, Any]:
    """Gaussian-copula correlation for teammates (by position pair) and for opponents."""
    keyed = _starter_rows(rows.filter(pl.col("scoring_preset") == "PPR")).join(
        dataset.filter(pl.col("scoring_preset") == "PPR").select(
            "season",
            "target_week",
            "player_id",
            "team",
            "opponent",
            "game_id",
        ),
        on=["season", "target_week", "player_id"],
        how="inner",
    )
    keyed = keyed.with_columns(pl.Series("pit", _pit(keyed)))
    left = keyed.select("game_id", "team", "position", "player_id", "pit")
    pairs = left.join(left, on="game_id", suffix="_b").filter(
        pl.col("player_id") < pl.col("player_id_b"),
    )
    result: dict[str, Any] = {"method": "spearman of PIT values -> 2 sin(pi r / 6)", "pairs": {}}
    groups: dict[str, pl.DataFrame] = {}
    teammates = pairs.filter(pl.col("team") == pl.col("team_b"))
    for row in (
        teammates.with_columns(
            pl.when(pl.col("position") <= pl.col("position_b"))
            .then(pl.col("position") + "-" + pl.col("position_b"))
            .otherwise(pl.col("position_b") + "-" + pl.col("position"))
            .alias("pair"),
        )
        .partition_by("pair", as_dict=True)
        .items()
    ):
        groups[f"teammates:{row[0][0]}"] = row[1]
    groups["opponents:any"] = pairs.filter(pl.col("team") != pl.col("team_b"))
    for key, frame in sorted(groups.items()):
        if frame.height < 200:
            continue
        rank_a = frame.get_column("pit").rank().to_numpy()
        rank_b = frame.get_column("pit_b").rank().to_numpy()
        spearman = float(np.corrcoef(rank_a, rank_b)[0, 1])
        result["pairs"][key] = {
            "pairs": frame.height,
            "spearman": round(spearman, 4),
            "rho": round(2.0 * math.sin(math.pi * spearman / 6.0), 4),
        }
    return result


def startable_thresholds(dataset: pl.DataFrame) -> dict[str, Any]:
    """Per league preset, scoring preset and position: the last starter's points, averaged.

    Every week's actual scores fill every roster's lineup in order — positions first, then
    FLEX from the best remaining backs, receivers and tight ends — and the threshold is the
    lowest score that still started at each position. Seasons before the sealed one only.
    """
    league = load_app_config().league
    scored = dataset.filter(pl.col("season") < WEEKLY_SEALED_SEASON)
    result: dict[str, Any] = {}
    for preset_id in sorted(league.presets):
        preset = league.preset(preset_id)
        teams = int(preset.teams)
        starters = {
            position: int(preset.starters.get(position, 0)) for position in WEEKLY_POSITIONS
        }
        flex = int(preset.starters.get("FLEX", 0))
        eligible = {str(position) for position in preset.flex_eligible}
        by_scoring: dict[str, dict[str, float | None]] = {}
        for (scoring,), block in scored.partition_by("scoring_preset", as_dict=True).items():
            lows: dict[str, list[float]] = {position: [] for position in WEEKLY_POSITIONS}
            for _, week in block.partition_by(["season", "target_week"], as_dict=True).items():
                taken: dict[str, list[float]] = {}
                leftovers: list[tuple[float, str]] = []
                for position in WEEKLY_POSITIONS:
                    points = sorted(
                        week.filter(pl.col("position") == position)
                        .get_column(TARGET_COLUMN)
                        .to_list(),
                        reverse=True,
                    )
                    count = teams * starters[position]
                    taken[position] = points[:count]
                    if position in eligible:
                        leftovers.extend((value, position) for value in points[count:])
                for value, position in sorted(leftovers, reverse=True)[: teams * flex]:
                    taken[position].append(value)
                for position, values in taken.items():
                    if values:
                        lows[position].append(min(values))
            by_scoring[str(scoring)] = {
                position: round(float(np.mean(values)), 2) if values else None
                for position, values in lows.items()
            }
        result[preset_id] = by_scoring
    return result


def publishable_measurements(
    *,
    dataset: pl.DataFrame,
    development_rows: pl.DataFrame,
    holdout_rows: pl.DataFrame,
    injuries: pl.DataFrame,
    appearances: pl.DataFrame,
    development: Mapping[str, Any],
    holdout: Mapping[str, Any],
) -> dict[str, Any]:
    """Everything the build copies into ``ros_build_metadata.weekly``, measured once."""
    out_of_fold = pl.concat([development_rows, holdout_rows], how="vertical_relaxed")
    candidate = holdout["pooled"][CANDIDATE_ID]
    return {
        "margin": margin_uncertainty(out_of_fold),
        "correlation": same_game_correlation(out_of_fold, dataset),
        "startable": startable_thresholds(dataset),
        "injuries": injury_base_rates(
            injuries,
            appearances,
            seasons=sorted({int(value) for value in dataset.get_column("season").unique()}),
        ),
        "evaluation": {
            "development_verdict": development["verdict"]["passed"],
            "holdout_verdict": holdout["verdict"]["passed"],
            "holdout_season": WEEKLY_SEALED_SEASON,
            "holdout_pairs": candidate["pairs"],
            "holdout_pair_accuracy": candidate["pair_accuracy"],
            "holdout_pair_brier": candidate["pair_brier"],
            "holdout_coverage_80": candidate["coverage_80"],
            "holdout_coverage_50": candidate["coverage_50"],
            "best_baseline_pair_accuracy": max(
                holdout["pooled"][baseline]["pair_accuracy"] for baseline in holdout["baselines"]
            ),
            "calibration": holdout["diagnostics"]["calibration"],
        },
    }
