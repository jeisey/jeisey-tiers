"""Simulated VORP distributions: the draw loop around the canonical allocation.

`docs/MODELING.md` sections 11 and 12 describe one procedure, and this module is the loop
that runs it many times:

1. sample every player's season total from his own monotone quantile function;
2. hand that whole draw to :func:`ffdraft.simulation.allocation.allocate_starters`, which
   fills the mandatory positional slots, competes the FLEX globally and reports the best
   player nobody started at each position;
3. subtract that draw's replacement baseline from that draw's points.

**Replacement varies by draw, and that is the entire point.** Subtracting one fixed
replacement value from every quantile of a player's point distribution would describe a
league whose scarcity is known in advance; it would make VORP a shifted copy of points and
would understate the uncertainty at exactly the positions where scarcity is uncertain. Here
the baseline is resampled with everybody else, so a draw where the top running backs all
collapse is a draw where replacement is low and the surviving backs are worth more.

There is **one** allocation implementation in this repository. Phase 2 feeds it realized
season totals to build the historical VORP labels; this module feeds it Monte Carlo draws.
Nothing here re-derives who a league starts.

Determinism comes from :mod:`ffdraft.simulation.sampler`: the point draws are a pure
function of the model version, the simulation version, the scoring preset, the seed material
and each player's own id. They deliberately do **not** depend on the league preset, so the
same simulated seasons are re-allocated under 10-, 12- and 14-team rules and a difference
between presets is a difference in roster shape rather than in Monte Carlo noise.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.config import LeaguePreset
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.simulation.allocation import PlayerPoints, allocate_starters
from ffdraft.simulation.sampler import (
    SIMULATION_VERSION,
    DomainBounds,
    QuantileFunction,
)

__all__ = [
    "REPLACEMENT_UNAVAILABLE_FLAG",
    "SimulationConfig",
    "SimulationResult",
    "fair_ranking",
    "quantile_column_names",
    "sample_points",
    "simulate_vorp",
]

Floats = NDArray[np.float64]

#: Recorded on a player whose position had no replacement baseline in at least one draw.
REPLACEMENT_UNAVAILABLE_FLAG = "replacement_unavailable"


def quantile_column_names(prefix: str, levels: Sequence[float] = QUANTILE_LEVELS) -> list[str]:
    return [f"p{int(level * 100):02d}_{prefix}" for level in levels]


@dataclass(frozen=True)
class SimulationConfig:
    """Everything a simulated VORP distribution is a function of."""

    draws: int
    seed: int
    model_version: str
    scoring_preset: str
    build_id: str = ""
    simulation_version: str = SIMULATION_VERSION
    levels: tuple[float, ...] = QUANTILE_LEVELS

    @property
    def seed_material(self) -> tuple[object, ...]:
        """What the per-player uniform streams are derived from.

        The league preset is deliberately absent: the same simulated seasons are allocated
        under every roster shape, so a preset-to-preset difference in VORP is a difference in
        scarcity rather than in the draws.
        """
        return (
            self.model_version,
            self.simulation_version,
            self.scoring_preset,
            self.build_id,
            self.seed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "draws": self.draws,
            "seed": self.seed,
            "model_version": self.model_version,
            "simulation_version": self.simulation_version,
            "scoring_preset": self.scoring_preset,
            "build_id": self.build_id,
            "levels": list(self.levels),
            "seed_material": [str(part) for part in self.seed_material],
            "player_draws_depend_on_league_preset": False,
        }


@dataclass(frozen=True)
class SimulationResult:
    """One (scoring preset, league preset) simulation."""

    league_preset_id: str
    scoring_preset: str
    config: SimulationConfig
    players: pl.DataFrame
    replacement: list[dict[str, Any]] = field(default_factory=list)
    unfilled_slots: Mapping[str, int] = field(default_factory=dict)
    #: The raw draw matrices, kept only when a caller asks. The tier stability bootstrap
    #: resamples the *simulated seasons*, so it needs the per-draw values rather than the
    #: summary; nothing else does, and 1,100 players x 10,000 draws is 88 MB per preset.
    vorp_draws: Floats | None = None
    point_draws: Floats | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "league_preset_id": self.league_preset_id,
            "scoring_preset": self.scoring_preset,
            "players": self.players.height,
            "configuration": self.config.to_dict(),
            "replacement": self.replacement,
            "unfilled_slots": dict(self.unfilled_slots),
        }


def sample_points(
    projections: pl.DataFrame,
    *,
    config: SimulationConfig,
    bounds: Mapping[str, DomainBounds],
    quantile_columns: Sequence[str] | None = None,
) -> Floats:
    """``(n_players, draws)`` sampled season totals, in the frame's row order.

    ``projections`` needs ``player_id``, ``position`` and one column per quantile level.
    Domain bounds are per position, so each position's pool is sampled through its own
    quantile function and the blocks are reassembled in the caller's row order.
    """
    columns = list(quantile_columns or quantile_column_names("points", config.levels))
    matrix = projections.select(columns).to_numpy().astype(np.float64)
    positions = projections.get_column("position").to_list()
    player_ids = projections.get_column("player_id").to_list()
    output = np.empty((len(player_ids), config.draws), dtype=np.float64)
    for position in sorted(set(positions)):
        rows = [index for index, value in enumerate(positions) if value == position]
        function = QuantileFunction(
            levels=tuple(config.levels),
            quantiles=matrix[rows, :],
            bounds=bounds.get(position, DomainBounds(float("-inf"), float("inf"))),
        )
        output[rows, :] = function.sample(
            [player_ids[index] for index in rows],
            config.draws,
            seed_material=config.seed_material,
        )
    return output


def simulate_vorp(
    projections: pl.DataFrame,
    *,
    preset: LeaguePreset,
    config: SimulationConfig,
    bounds: Mapping[str, DomainBounds],
    points: Floats | None = None,
    keep_draws: bool = False,
) -> SimulationResult:
    """Run the draw loop for one league preset and summarise it.

    ``points`` may be supplied when several presets share one set of draws, which is the
    normal production path: the same simulated seasons are allocated under every roster
    shape.
    """
    sampled = sample_points(projections, config=config, bounds=bounds) if points is None else points
    player_ids = projections.get_column("player_id").to_list()
    positions = projections.get_column("position").to_list()
    draws = sampled.shape[1]

    position_index: dict[str, list[int]] = {}
    for index, position in enumerate(positions):
        position_index.setdefault(position, []).append(index)

    vorp = np.empty_like(sampled)
    replacement_series: dict[str, Floats] = {
        position: np.full(draws, np.nan) for position in position_index
    }
    unavailable: dict[str, int] = dict.fromkeys(position_index, 0)
    unfilled_total: dict[str, int] = {}

    for draw in range(draws):
        column = sampled[:, draw]
        allocation = allocate_starters(
            [
                PlayerPoints(player_id=player_ids[index], position=positions[index], points=value)
                for index, value in enumerate(column)
            ],
            preset,
        )
        for position, rows in position_index.items():
            baseline = allocation.replacement_points.get(position)
            if baseline is None:
                unavailable[position] += 1
                vorp[rows, draw] = np.nan
            else:
                replacement_series[position][draw] = baseline
                vorp[rows, draw] = column[rows] - baseline
        for slot, count in allocation.unfilled_slots.items():
            unfilled_total[slot] = max(unfilled_total.get(slot, 0), count)

    levels = list(config.levels)
    point_quantiles = np.quantile(sampled, levels, axis=1).T
    # A position whose pool is entirely consumed by starting slots has no replacement
    # baseline in that draw, so its VORP is null by design rather than by accident. NumPy
    # warns about the all-NaN reduction that follows; the null is the intended answer.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        vorp_quantiles = np.nanquantile(vorp, levels, axis=1).T
        expected_vorp = np.nanmean(vorp, axis=1)
    expected_points = np.mean(sampled, axis=1)

    flags = [
        REPLACEMENT_UNAVAILABLE_FLAG if unavailable.get(position, 0) else ""
        for position in positions
    ]
    summary = projections.select("player_id", "position").with_columns(
        pl.lit(preset.preset_id).alias("league_preset_id"),
        pl.lit(config.scoring_preset).alias("scoring_preset"),
        pl.Series("expected_points", expected_points, dtype=pl.Float64),
        *[
            pl.Series(name, point_quantiles[:, index], dtype=pl.Float64)
            for index, name in enumerate(quantile_column_names("points", config.levels))
        ],
        pl.Series("expected_vorp", expected_vorp, dtype=pl.Float64),
        *[
            pl.Series(name, vorp_quantiles[:, index], dtype=pl.Float64)
            for index, name in enumerate(quantile_column_names("vorp", config.levels))
        ],
        pl.Series("quality_flags", flags, dtype=pl.Utf8),
    )
    summary = summary.with_columns(
        (pl.col("p75_vorp") - pl.col("p25_vorp")).alias("uncertainty"),
    )

    replacement = [
        {
            "position": position,
            "mean": float(np.nanmean(series)) if np.any(~np.isnan(series)) else None,
            **{
                f"p{int(level * 100):02d}": (
                    float(np.nanquantile(series, level)) if np.any(~np.isnan(series)) else None
                )
                for level in levels
            },
            "draws_without_replacement": int(unavailable.get(position, 0)),
        }
        for position, series in sorted(replacement_series.items())
    ]
    return SimulationResult(
        league_preset_id=preset.preset_id,
        scoring_preset=config.scoring_preset,
        config=config,
        players=summary,
        replacement=replacement,
        unfilled_slots=unfilled_total,
        vorp_draws=vorp if keep_draws else None,
        point_draws=sampled if keep_draws else None,
    )


#: The ranking statistics `phase4_ranking_v1` chooses between.
RANK_STATISTIC_COLUMN: Mapping[str, str] = {
    "median_vorp": "p50_vorp",
    "expected_vorp": "expected_vorp",
}


def fair_ranking(players: pl.DataFrame, *, statistic: str) -> pl.DataFrame:
    """Add ``fair_rank`` and ``position_rank`` under one ranking statistic.

    The tie-break is `docs/DATA_CONTRACTS.md` section 7's, in its declared order: the
    ranking statistic, then P50 points, then lower uncertainty, then a stable ``player_id``.
    A player whose position had no replacement baseline in any draw sorts last rather than
    being dropped, because a null VORP is a statement about the league's depth, not about
    the player.
    """
    column = RANK_STATISTIC_COLUMN.get(statistic)
    if column is None:
        raise ValueError(
            f"unknown ranking statistic {statistic!r}; known: {sorted(RANK_STATISTIC_COLUMN)}",
        )
    ordered = players.sort(
        [column, "p50_points", "uncertainty", "player_id"],
        descending=[True, True, False, False],
        nulls_last=True,
    ).with_row_index("_row")
    return (
        ordered.with_columns(
            (pl.col("_row") + 1).cast(pl.Int32).alias("fair_rank"),
        )
        .with_columns(
            pl.col("fair_rank")
            .rank("ordinal")
            .over("position")
            .cast(pl.Int32)
            .alias(
                "position_rank",
            ),
        )
        .drop("_row")
    )
