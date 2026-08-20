"""The deterministic Monte Carlo sampler.

The production model emits five quantiles per player, not a parametric distribution, so
`docs/MODELING.md` section 11 says what to do with them: build a monotone piecewise-linear
quantile function, draw a uniform, and read the value off it. This module is that, plus the
two properties the rest of Phase 4 depends on.

**Monotone by construction.** A :class:`QuantileFunction` refuses to be built from a
crossing grid. Repairing crossings is :mod:`ffdraft.modeling.calibration`'s job and happens
upstream, so by the time a distribution reaches the sampler the question is already settled
and the sampler can assume it rather than silently sorting.

**Tails are one documented rule, not a fitted family.** Five quantiles do not identify a
tail. Outside the supported levels the function continues the slope of the nearest interior
segment and then clamps to declared domain bounds. That is deliberately unambitious: it
cannot invent a 700-point season, and it does not pretend to know the shape of a tail it has
no evidence about. Fantasy season totals *can* be negative under this project's scoring
presets - interceptions and lost fumbles both cost points - so nothing is clamped at zero;
the floor comes from the observed training range instead.

**Determinism is per player, not per pool.** Each player's uniform stream is derived from
the build's seed material and the player's own id, so a player's draws do not change when
another player enters or leaves the pool. Two runs with the same model version, simulation
version, scoring preset and seed produce bit-identical draws.

Draws are independent across players. V1 does not model teammate or game-script correlation,
and `docs/MODELING.md` section 23 states that limitation publicly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DEFAULT_LOWER_MARGIN",
    "DEFAULT_UPPER_MARGIN",
    "SIMULATION_VERSION",
    "DomainBounds",
    "QuantileFunction",
    "normal_draws",
    "seed_material_int",
    "uniform_draws",
]

Floats = NDArray[np.float64]

#: Bump when the sampling rule changes in a way that moves numbers. Recorded in model
#: metadata and in every simulated artifact, next to the model version.
SIMULATION_VERSION = "mc_quantile_sampler_v1"

#: How far below the observed training range the floor sits, as a share of that range.
#: Small, because a season total far below the worst ever observed is not a thing football
#: produces - the downside is bounded by "played almost nothing", which is near zero.
DEFAULT_LOWER_MARGIN = 0.05

#: How far above it the cap sits. Larger, because records genuinely fall: a rookie beating
#: the best receiving season in the training window is a real possibility a draft board
#: should be able to express.
DEFAULT_UPPER_MARGIN = 0.15


@dataclass(frozen=True, slots=True)
class DomainBounds:
    """The values a sampled season total may take.

    Derived from the *training* range only, so the bounds carry no information about the
    season being predicted. They are guard rails on the extrapolated tails rather than a
    shaping device: inside the supported quantile levels they never bind.
    """

    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not self.lower <= self.upper:
            raise ValueError(f"domain bounds are inverted: [{self.lower}, {self.upper}]")

    @classmethod
    def from_training(
        cls,
        values: Sequence[float] | Floats,
        *,
        lower_margin: float = DEFAULT_LOWER_MARGIN,
        upper_margin: float = DEFAULT_UPPER_MARGIN,
    ) -> DomainBounds:
        array = np.asarray(values, dtype=np.float64)
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return cls(float("-inf"), float("inf"))
        low = float(np.min(finite))
        high = float(np.max(finite))
        span = high - low
        return cls(low - lower_margin * span, high + upper_margin * span)

    def clamp(self, values: Floats) -> Floats:
        return np.clip(values, self.lower, self.upper)

    def to_dict(self) -> dict[str, float]:
        return {"lower": self.lower, "upper": self.upper}


@dataclass(frozen=True)
class QuantileFunction:
    """A monotone piecewise-linear quantile function per player.

    ``quantiles`` is ``(n_players, n_levels)`` and must be non-decreasing along each row.
    ``levels`` is the shared, strictly increasing level grid.
    """

    levels: tuple[float, ...]
    quantiles: Floats
    bounds: DomainBounds

    def __post_init__(self) -> None:
        grid = np.asarray(self.levels, dtype=np.float64)
        if grid.size < 2:
            raise ValueError("a quantile function needs at least two supported levels")
        if np.any(np.diff(grid) <= 0.0):
            raise ValueError(f"quantile levels must be strictly increasing, got {self.levels}")
        matrix = np.asarray(self.quantiles, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != grid.size:
            raise ValueError(
                f"quantile matrix {matrix.shape} does not match {grid.size} level(s)",
            )
        if not np.all(np.isfinite(matrix)):
            raise ValueError("a quantile function cannot contain a non-finite value")
        if matrix.size and np.any(np.diff(matrix, axis=1) < 0.0):
            rows = int(np.count_nonzero(np.any(np.diff(matrix, axis=1) < 0.0, axis=1)))
            raise ValueError(
                f"{rows} row(s) have crossing quantiles; repair monotonicity before sampling",
            )

    @property
    def n_players(self) -> int:
        return int(self.quantiles.shape[0])

    def evaluate(self, u: Floats) -> Floats:
        """Value at uniform ``u``.

        ``u`` is ``(n_players, draws)`` or broadcastable to it. Interior points interpolate
        linearly between the two supported levels that bracket them; exterior points
        continue the slope of the nearest interior segment and are then clamped to the
        domain bounds. One formula covers both because the segment index is clipped rather
        than special-cased, which is also why there is no discontinuity at P10 or P90.
        """
        grid = np.asarray(self.levels, dtype=np.float64)
        values = np.asarray(u, dtype=np.float64)
        last = grid.size - 2
        index = np.clip(np.searchsorted(grid, values, side="right") - 1, 0, last)
        lower_level = grid[index]
        upper_level = grid[index + 1]
        rows = np.arange(self.quantiles.shape[0])[:, None] if values.ndim == 2 else slice(None)
        lower_value = self.quantiles[rows, index]
        upper_value = self.quantiles[rows, index + 1]
        fraction = (values - lower_level) / (upper_level - lower_level)
        return self.bounds.clamp(lower_value + fraction * (upper_value - lower_value))

    def sample(
        self,
        player_ids: Sequence[str],
        draws: int,
        *,
        seed_material: Sequence[object],
    ) -> Floats:
        """``(n_players, draws)`` sampled values, deterministic in ids and seed material."""
        if len(player_ids) != self.n_players:
            raise ValueError(
                f"{len(player_ids)} player id(s) for {self.n_players} quantile row(s)",
            )
        return self.evaluate(uniform_draws(player_ids, draws, seed_material=seed_material))

    def probability_integral_transform(self, values: Floats) -> Floats:
        """Where an observed value sits on each player's own quantile function.

        The inverse of :meth:`evaluate` for interior values, used to estimate the dependence
        parameter between two components from their realized outcomes. A value landing on a
        flat segment - which is common for games played, where the lowest quantiles are all
        zero - is placed at the midpoint of that segment's level interval, because the
        function genuinely cannot distinguish inside a flat region.
        """
        grid = np.asarray(self.levels, dtype=np.float64)
        observed = np.asarray(values, dtype=np.float64)
        if observed.shape != (self.n_players,):
            raise ValueError(f"expected {self.n_players} value(s), got {observed.shape}")
        last = grid.size - 2
        index = np.clip(np.sum(self.quantiles < observed[:, None], axis=1) - 1, 0, last)
        rows = np.arange(self.n_players)
        lower_value = self.quantiles[rows, index]
        upper_value = self.quantiles[rows, index + 1]
        lower_level = grid[index]
        upper_level = grid[index + 1]
        span = upper_value - lower_value
        fraction = np.where(
            span > 0.0, (observed - lower_value) / np.where(span > 0.0, span, 1.0), 0.5
        )
        return np.clip(lower_level + fraction * (upper_level - lower_level), 1e-6, 1.0 - 1e-6)

    def describe(self) -> dict[str, Any]:
        return {
            "simulation_version": SIMULATION_VERSION,
            "levels": list(self.levels),
            "players": self.n_players,
            "bounds": self.bounds.to_dict(),
            "interpolation": "monotone piecewise linear between supported levels",
            "tails": (
                "linear continuation of the nearest interior segment, clamped to the "
                "training-range domain bounds"
            ),
        }


def _stable_int(text: str) -> int:
    """A machine-independent 64-bit integer from a string.

    Python's ``hash`` is salted per process, so it cannot appear anywhere near a
    reproducible seed. BLAKE2b is stable across runs, platforms and interpreter versions.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def seed_material_int(seed_material: Sequence[object]) -> int:
    """Fold declared seed material - model version, preset, build id, seed - into one int."""
    rendered = "|".join(str(part) for part in seed_material)
    return _stable_int(rendered)


def _generator(master: int, player_id: str) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([master, _stable_int(player_id)]))


def uniform_draws(
    player_ids: Sequence[str],
    draws: int,
    *,
    seed_material: Sequence[object],
) -> Floats:
    """``(n_players, draws)`` uniforms, one independent stream per player.

    Seeding per player rather than per pool is what makes a player's simulated outcomes
    independent of who else is in the pool: adding a rookie to the board does not move
    anybody else's floor or ceiling by a Monte Carlo accident.
    """
    if draws <= 0:
        raise ValueError(f"draws must be positive, got {draws}")
    master = seed_material_int(seed_material)
    output = np.empty((len(player_ids), draws), dtype=np.float64)
    for row, player_id in enumerate(player_ids):
        output[row] = _generator(master, player_id).random(draws)
    return output


def normal_draws(
    player_ids: Sequence[str],
    draws: int,
    *,
    seed_material: Sequence[object],
    streams: int = 2,
) -> Floats:
    """``(streams, n_players, draws)`` independent standard normals per player.

    Used by the copula in Candidate B, which needs two coupled streams per player. Drawing
    both from the same per-player generator keeps the whole composition reproducible from
    the same seed material as everything else.
    """
    if draws <= 0:
        raise ValueError(f"draws must be positive, got {draws}")
    if streams <= 0:
        raise ValueError(f"streams must be positive, got {streams}")
    master = seed_material_int(seed_material)
    output = np.empty((streams, len(player_ids), draws), dtype=np.float64)
    for row, player_id in enumerate(player_ids):
        block = _generator(master, player_id).standard_normal((streams, draws))
        output[:, row, :] = block
    return output
